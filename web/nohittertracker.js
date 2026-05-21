let secondsSinceLastUpdated = 0;
let updateInterval;
let autoRefreshInterval;
let scheduleRequestInFlight = false;
let unfilteredGamesHtml;
let isDarkMode = true;
const openPitcherDetailsGameIds = new Set();
const highlightedGameIds = new Set();
let unfilteredCardHtmlByGameId = {};
let unfilteredCardOrder = [];
const HIGHLIGHTED_GAMES_STORAGE_KEY = 'highlightedGames';

// Default for local development. Overridden at runtime by web/config.json.
let API_BASE_URL = 'http://127.0.0.1:8001';
const MLB_TEAMS_API_URL = 'https://statsapi.mlb.com/api/v1/teams?sportId=1';

$(document).ready(function() {
    const initialDate = getDateFromQueryParam() || new Date();
    const currentDateFormatted = getFormattedDate(initialDate);
    initDatePicker(currentDateFormatted);
    initDateArrows();
    initTodayButton();
    initFavoriteTeam();
    initAutoRefresh();
    updateLastUpdatedVisibility();

    $.getJSON('config.json')
        .done(function(cfg) {
            if (cfg && cfg.apiBaseUrl) API_BASE_URL = cfg.apiBaseUrl;
        })
        .always(function() {
            makeScheduleRequest(currentDateFormatted);
        });

    $('#gamesContainer').on('mouseenter', '.startTimeTip', function() {
        const text = getTimeUntilStart($(this).data('start-time'));
        if (text) {
            $(this).attr('data-tooltip', text).addClass('startTimeTipVisible');
        }
    }).on('mouseleave', '.startTimeTip', function() {
        $(this).removeClass('startTimeTipVisible');
    });
});

function isSelectedDateToday() {
    const selected = $('#datepicker').datepicker('getDate');
    if (!selected) return false;
    const today = new Date();
    return selected.getFullYear() === today.getFullYear() &&
           selected.getMonth() === today.getMonth() &&
           selected.getDate() === today.getDate();
}

function getTodayDateString() {
    const today = new Date();
    return getFormattedDate(today);
}

function loadHighlightedGamesForSelectedDate() {
    highlightedGameIds.clear();
    if (!isSelectedDateToday()) return;

    try {
        const raw = localStorage.getItem(HIGHLIGHTED_GAMES_STORAGE_KEY);
        if (!raw) return;

        const stored = JSON.parse(raw);
        if (!stored || stored.date !== getTodayDateString()) {
            localStorage.removeItem(HIGHLIGHTED_GAMES_STORAGE_KEY);
            return;
        }

        if (Array.isArray(stored.ids)) {
            stored.ids.forEach(id => highlightedGameIds.add(String(id)));
        }
    } catch (e) {
        highlightedGameIds.clear();
    }
}

function saveHighlightedGamesForSelectedDate() {
    if (!isSelectedDateToday()) return;

    try {
        const payload = { date: getTodayDateString(), ids: Array.from(highlightedGameIds) };
        localStorage.setItem(HIGHLIGHTED_GAMES_STORAGE_KEY, JSON.stringify(payload));
    } catch (e) {
        // Ignore storage errors (quota/privacy modes) and continue without persistence.
    }
}

function updateGameSelectionAvailability() {
    $('#gamesContainer').toggleClass('gamesSelectable', isSelectedDateToday());
}

function updateLastUpdatedVisibility() {
    if (isSelectedDateToday()) {
        $('#lastUpdated').show();
        return;
    }

    clearInterval(updateInterval);
    $('#lastUpdated').hide();
}

function updateTodayButtonVisibility() {
    $('#todayButton').toggle(!isSelectedDateToday());
}

function initAutoRefresh() {
    if (autoRefreshInterval !== null) {
        clearInterval(autoRefreshInterval);
    }

    autoRefreshInterval = setInterval(function() {
        const selectedDate = $('#datepicker').datepicker('getDate');
        if (!selectedDate || scheduleRequestInFlight || !isSelectedDateToday()) {
            return;
        }

        const selectedDateFormatted = getFormattedDate(selectedDate);
        makeScheduleRequest(selectedDateFormatted);
    }, 60000);
}

function initHighlightState() {
    const canSelectGames = isSelectedDateToday();

    document.querySelectorAll('.gameContainer').forEach(container => {
        const gameId = container.id;
        const isNoHitterCard = container.classList.contains('noHitterBackground');

        if (!canSelectGames) {
            container.classList.remove('gameHighlighted');
            return;
        }

        if (isNoHitterCard) {
            if (gameId) {
                highlightedGameIds.delete(gameId);
            }
            container.classList.remove('gameHighlighted');
        }

        if (gameId && highlightedGameIds.has(gameId)) {
            container.classList.add('gameHighlighted');
        }

        $(container)
            .off('mousedown.gameCard mouseup.gameCard mouseleave.gameCard click.gameCard')
            .on('mousedown.gameCard', function(e) {
                if (this.classList.contains('noHitterBackground')) return;
                if (e.target.closest('.pitcherDetailsSummary') || e.target.closest('.pitcherDetailsPanel')) return;
                this.classList.add('gameContainerPressed');
            })
            .on('mouseup.gameCard', function() {
                this.classList.remove('gameContainerPressed');
            })
            .on('mouseleave.gameCard', function() {
                this.classList.remove('gameContainerPressed');
            })
            .on('click.gameCard', function(e) {
                if (this.classList.contains('noHitterBackground')) return;
                if (e.target.closest('.pitcherDetailsSummary') || e.target.closest('.pitcherDetailsPanel')) return;
                const id = this.id;
                if (!id) return;
                if (highlightedGameIds.has(id)) {
                    highlightedGameIds.delete(id);
                    this.classList.remove('gameHighlighted');
                } else {
                    highlightedGameIds.add(id);
                    this.classList.add('gameHighlighted');
                }

                saveHighlightedGamesForSelectedDate();
            });
    });

    if (canSelectGames) {
        saveHighlightedGamesForSelectedDate();
    }
}

function initPitcherDetailsState() {
    document.querySelectorAll('.pitcherDetails').forEach(details => {
        const gameId = details.getAttribute('data-game-id');
        if (gameId && openPitcherDetailsGameIds.has(gameId)) {
            details.open = true;
        }

        $(details).off('toggle.pitcherDetails').on('toggle.pitcherDetails', function() {
            const currentGameId = this.getAttribute('data-game-id');
            if (!currentGameId) {
                return;
            }

            if (this.open) {
                openPitcherDetailsGameIds.add(currentGameId);
            } else {
                openPitcherDetailsGameIds.delete(currentGameId);
            }
        });

        if (details.open) {
            openPitcherDetailsGameIds.add(gameId);
        }
    });
}

function initDatePicker(initialDate) {
    const now = new Date();
    const minSelectableDate = new Date(1901, 0, 1);
    const maxSelectableDate = new Date(now.getFullYear() + 1, 11, 31);

    $('#datepicker').datepicker({
        changeMonth: true,
        changeYear: true,
        minDate: minSelectableDate,
        maxDate: maxSelectableDate,
        yearRange: `1901:${maxSelectableDate.getFullYear()}`,
        onSelect: function(dateText, i) {
            if (dateText !== i.lastVal) {
                $(this).change();
            }
        }
    });
    $('#datepicker').datepicker('setDate', initialDate);
    loadHighlightedGamesForSelectedDate();
    updateGameSelectionAvailability();
    updateTodayButtonVisibility();

    $('#datepicker').change(function() {
        handleDatePickerChange();
    });
}

function initDateArrows() {
    $('#arrowLeftContainer').click(function() {
        const currentDateVal = $('#datepicker').datepicker('getDate');
        const newDate = currentDateVal;
        newDate.setDate(currentDateVal.getDate() - 1);
        $('#datepicker').datepicker('setDate', newDate);
        handleDatePickerChange();
    });

    $('#arrowRightContainer').click(function() {
        const currentDateVal = $('#datepicker').datepicker('getDate');
        const newDate = currentDateVal;
        newDate.setDate(currentDateVal.getDate() + 1);
        $('#datepicker').datepicker('setDate', newDate);
        handleDatePickerChange();
    });
}

function initTodayButton() {
    $('#todayButton').click(function() {
        const today = new Date();
        $('#datepicker').datepicker('setDate', today);
        updateDateQueryParam(null);
        handleDatePickerChange();
    });

    updateTodayButtonVisibility();
}

function handleDatePickerChange() {
    const selectedDate = $('#datepicker').datepicker('getDate');
    const selectedDateFormatted = getFormattedDate(selectedDate);
    updateDateQueryParam(selectedDate);
    loadHighlightedGamesForSelectedDate();
    updateGameSelectionAvailability();
    updateTodayButtonVisibility();
    updateLastUpdatedVisibility();
    $('#loaderContainer').show();
    $('#gamesMessage').hide();
    makeScheduleRequest(selectedDateFormatted);
}

// Updates (or removes) the ?date= query param in the URL without reloading the page.
// Pass null to remove the param (i.e. when today is selected).
function updateDateQueryParam(dateObj) {
    const today = new Date();
    const isToday = dateObj &&
        dateObj.getFullYear() === today.getFullYear() &&
        dateObj.getMonth() === today.getMonth() &&
        dateObj.getDate() === today.getDate();

    const params = new URLSearchParams(window.location.search);
    if (!dateObj || isToday) {
        params.delete('date');
    } else {
        const yyyy = dateObj.getFullYear();
        const mm = String(dateObj.getMonth() + 1).padStart(2, '0');
        const dd = String(dateObj.getDate()).padStart(2, '0');
        params.set('date', `${yyyy}-${mm}-${dd}`);
    }
    const newSearch = params.toString() ? `?${params.toString()}` : '';
    history.replaceState(null, '', `${window.location.pathname}${newSearch}`);
}

// Parses a ?date=YYYY-MM-DD query parameter and returns a Date, or null on failure.
function getDateFromQueryParam() {
    try {
        const params = new URLSearchParams(window.location.search);
        const raw = params.get('date');
        if (!raw) return null;
        const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
        if (!match) return null;
        const year = parseInt(match[1], 10);
        const month = parseInt(match[2], 10) - 1; // 0-indexed
        const day = parseInt(match[3], 10);
        const date = new Date(year, month, day);
        // Verify components to catch invalid dates like Feb 30
        if (date.getFullYear() !== year || date.getMonth() !== month || date.getDate() !== day) return null;
        return date;
    } catch (e) {
        return null;
    }
}

function getFormattedDate(dateObj) {
    const currentMonth = dateObj.getMonth() + 1;
    const currentDay = dateObj.getDate();
    const currentYear = dateObj.getFullYear();
    return `${currentMonth}/${currentDay}/${currentYear}`;
}

function initFavoriteTeam() {
    const $favoriteTeam = $('#favoriteTeam');

    $favoriteTeam.off('change').on('change', function() {
        const selectedTeam = $(this).val();
        localStorage.setItem('favoriteTeam', selectedTeam);
        adjustGamesForFavTeam();
    });

    return $.ajax({
        type: 'GET',
        url: MLB_TEAMS_API_URL,
        dataType: 'json'
    }).done(function(response) {
        const teams = (response && Array.isArray(response.teams) ? response.teams : [])
            .filter(team => team && team.active)
            .sort((a, b) => a.name.localeCompare(b.name));

        $favoriteTeam.empty().append('<option value="none">--None--</option>');
        teams.forEach(team => {
            $favoriteTeam.append(`<option value="${team.id}">${team.name}</option>`);
        });

        const storedVal = localStorage.getItem('favoriteTeam');
        if (storedVal && $favoriteTeam.find(`option[value="${storedVal}"]`).length > 0) {
            $favoriteTeam.val(storedVal);
        } else {
            $favoriteTeam.val('none');
            if (storedVal && storedVal !== 'none') {
                localStorage.setItem('favoriteTeam', 'none');
            }
        }

        if (unfilteredGamesHtml) {
            adjustGamesForFavTeam();
        }
    }).fail(function() {
        const storedVal = localStorage.getItem('favoriteTeam');
        if (storedVal !== null && $favoriteTeam.find(`option[value="${storedVal}"]`).length > 0) {
            $favoriteTeam.val(storedVal);
        } else {
            $favoriteTeam.val('none');
        }
    });
}

function setLastUpdated(seconds) {
    $('#lastUpdatedTime').text(seconds < 10 ? 'just now' : seconds + 's ago');

    if (updateInterval !== null) {
        clearInterval(updateInterval);
    }
    updateInterval = setInterval(function() {
        secondsSinceLastUpdated += 10;
        setLastUpdated(secondsSinceLastUpdated);
    }, 10000);
}

function getGameStatus(statusObj) {
    const gameCodeLive = statusObj.abstractGameCode === 'L';

    if (gameCodeLive && statusObj.codedGameState === 'I') {
        return 'I';
    }
    if (gameCodeLive && statusObj.codedGameState === 'P') {
        return 'P';
    }

    return statusObj.abstractGameCode;
}

function makeScheduleRequest(date) {
    if (scheduleRequestInFlight) {
        return;
    }

    scheduleRequestInFlight = true;

    return $.ajax({
        type: 'GET',
        url: `${API_BASE_URL}/api/games`,
        data: {
            date,
            include_events: true,
            include_event_snapshot: false,
            include_legacy: false
        },
        success: function(payload) {
            try {
                const gamesById = payload && payload.entities ? payload.entities.games_by_id : {};
                const orderedGameIds = payload && payload.entities ? payload.entities.game_ids_in_order : [];
                const events = payload && payload.activity ? payload.activity.events : [];

                let games;
                if (orderedGameIds && orderedGameIds.length > 0) {
                    games = orderedGameIds
                        .map(gameId => gamesById[gameId])
                        .filter(game => !!game);
                } else {
                    games = Object.keys(gamesById || {}).map(key => gamesById[key]);
                    games.sort((a, b) => {
                        const aTime = (((a || {}).gameData || {}).datetime || {}).dateTime || '9999-12-31T23:59:59Z';
                        const bTime = (((b || {}).gameData || {}).datetime || {}).dateTime || '9999-12-31T23:59:59Z';
                        return aTime.localeCompare(bTime);
                    });
                }

                if (games.length > 0) {
                    processGameInfoResults(games, events);
                    $('#gamesMessage').hide();
                    $('#gamesContainer').show();
                } else {
                    updateLastUpdatedVisibility();
                    if (isSelectedDateToday()) {
                        $('#lastUpdatedTime').text('n/a');
                    }
                    $('#gamesContainer').hide();
                    $('#gamesMessage').text('No games scheduled.').show();
                    $('#loaderContainer').hide();
                }
            } catch (e) {
                console.log(e);
            }

            scheduleRequestInFlight = false;
        },
        error: function() {
            $('#loaderContainer').hide();
            $('#gamesContainer').hide();
            $('#gamesMessage').text('Error retrieving games.').show();
            scheduleRequestInFlight = false;
        }
    });
}

function ordinalSuffix(n) {
    const s = ['th', 'st', 'nd', 'rd'];
    const v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

function buildBrokenPlayHtml(play) {
    if (!play) return '';
    const completedInnings = `${play.completed_innings}.${play.completed_outs}`;
    return `<p class="brokenPlayInfo">No-hitter broken up on a ${play.play_event} by ${play.batter_name} after ${completedInnings} innings.</p>`;
}

function processGameInfoResults(gameInfoResults, events) {
    const cardHtmlByGameId = {};
    const cardOrder = [];

    const brokenEventsByTeam = {};
    (events || []).forEach(event => {
        if (event.event_type === 'no_hitter_broken' && event.broken_play) {
            brokenEventsByTeam[`${event.game_id}:${event.team_id}`] = event.broken_play;
        }
    });

    gameInfoResults.forEach(gameInfoResult => {
        // Validate game structure
        if (!gameInfoResult || !gameInfoResult.gameData || !gameInfoResult.liveData) {
            console.warn('Skipping malformed game result:', gameInfoResult);
            return;
        }

        const gameId = gameInfoResult.gamePk;
        const gameData = gameInfoResult.gameData;
        const flags = gameData.flags;
        const liveData = gameInfoResult.liveData;
        const linescore = liveData.linescore;

        const gameStatus = getGameStatus(gameData.status);
        const isGameInProgress = gameStatus === 'I';
        const isGameFinal = gameStatus === 'F';
        const isGameStatusSpecial = ['PPD', 'IR', 'DR', 'DO', 'DS'].includes(gameData.status.statusCode);
        const gameStatusDetailed = gameData.status.detailedState === 'Game Over' ? 'Final' : gameData.status.detailedState;
        const currentInning = linescore.currentInning;
        const isTopInning = linescore.isTopInning;
        const innings = linescore.innings;
        const time = getTimeStringFromUTC(gameData.datetime.dateTime);
        const teams = gameData.teams;

        const numBalls = linescore.balls;
        const numStrikes = linescore.strikes;
        const numOuts = linescore.outs;
        const isRunnerOnFirst = linescore.offense.hasOwnProperty('first');
        const isRunnerOnSecond = linescore.offense.hasOwnProperty('second');
        const isRunnerOnThird = linescore.offense.hasOwnProperty('third');

        const homeTeam = teams.home;
        const boxScoreHome = liveData.boxscore.teams.home;
        const homeTeamStats = boxScoreHome.teamStats;

        const homeTeamName = homeTeam.name;
        const homeTeamAbbrv = homeTeam.abbreviation;
        const homeTeamNumPitchers = boxScoreHome.pitchers ? boxScoreHome.pitchers.length : 0;
        const homeTeamPitcherName = boxScoreHome.pitcherName || '';
        const homeTeamPitcherStats = boxScoreHome.pitcherStats || '';
        const homeTeamPitcherLines = boxScoreHome.pitcherLines || [];
        const homeTeamRuns = homeTeamStats.batting.runs;
        const homeTeamHits = homeTeamStats.batting.hits;
        const homeTeamErrors = homeTeamStats.fielding.errors;
        const homeTeamWalks = homeTeamStats.batting.baseOnBalls;
        const homeTeamHBPs = homeTeamStats.batting.hitByPitch;

        const awayTeam = teams.away;
        const boxScoreAway = liveData.boxscore.teams.away;
        const awayTeamStats = boxScoreAway.teamStats;

        const awayTeamName = awayTeam.name;
        const awayTeamAbbrv = awayTeam.abbreviation;
        const awayTeamNumPitchers = boxScoreAway.pitchers ? boxScoreAway.pitchers.length : 0;
        const awayTeamPitcherName = boxScoreAway.pitcherName || '';
        const awayTeamPitcherStats = boxScoreAway.pitcherStats || '';
        const awayTeamPitcherLines = boxScoreAway.pitcherLines || [];
        const awayTeamRuns = awayTeamStats.batting.runs;
        const awayTeamHits = awayTeamStats.batting.hits;
        const awayTeamErrors = awayTeamStats.fielding.errors;
        const awayTeamWalks = awayTeamStats.batting.baseOnBalls;
        const awayTeamHBPs = awayTeamStats.batting.hitByPitch;

        const numInningHeadings = innings.length < 9 ? 9 : innings.length;
        let inningsHeadingHtml = '';
        for (let i = 1; i <= numInningHeadings; i++) {
            inningsHeadingHtml += `<th>${i}</th>`;
        }

        let inningsHomeHtml = '';
        let inningsAwayHtml = '';

        const getHalfInningRuns = (halfInningData, isCurrentHalfInning) => {
            const runs = halfInningData && Object.prototype.hasOwnProperty.call(halfInningData, 'runs')
                ? halfInningData.runs
                : null;

            if (runs !== null && runs !== undefined) {
                return runs;
            }

            return isCurrentHalfInning ? '0' : '';
        };

        innings.forEach(inning => {
            const inningNum = inning.num;
            const isCurrentInning = isGameInProgress && inningNum === currentInning;
            const isTopCurrentHalf = isCurrentInning && isTopInning;
            const isBottomCurrentHalf = isCurrentInning && !isTopInning;

            const homeRuns = getHalfInningRuns(inning.home, isBottomCurrentHalf);
            const awayRuns = getHalfInningRuns(inning.away, isTopCurrentHalf);

            if (isCurrentInning) {
                inningsHomeHtml += !isTopInning ? `<td class="currentHalfInning">${homeRuns}</td>` : `<td>${homeRuns}</td>`;
                inningsAwayHtml += isTopInning ? `<td class="currentHalfInning">${awayRuns}</td>` : `<td>${awayRuns}</td>`;
            } else {
                inningsHomeHtml += (isGameFinal && homeRuns === '') ? '<td class="crossed"></td>' : `<td>${homeRuns}</td>`;
                inningsAwayHtml += (isGameFinal && awayRuns === '') ? '<td class="crossed"></td>' : `<td>${awayRuns}</td>`;
            }
        });

        for (let i = innings.length; i < numInningHeadings; i++) {
            inningsHomeHtml += isGameFinal ? '<td class="crossed"></td>' : '<td></td>';
            inningsAwayHtml += isGameFinal ? '<td class="crossed"></td>' : '<td></td>';
        }

        const homeTeamId = gameData.teams.home.id;
        const awayTeamId = gameData.teams.away.id;

        const homeTeamNoHitterStatus = flags.homeTeamNoHitterStatus || 'none';
        const homeTeamNoHitterParams = { isGameFinal, noHitterStatus: homeTeamNoHitterStatus, numPitchers: homeTeamNumPitchers, pitcherName: homeTeamPitcherName, playerTeamName: homeTeamName, playerTeamAbbreviation: homeTeamAbbrv, opposingTeamName: awayTeamName };
        const homeTeamNoHitterHtml = buildNoHitterHtml(homeTeamNoHitterParams);

        const awayTeamNoHitterStatus = flags.awayTeamNoHitterStatus || 'none';
        const awayTeamNoHitterParams = { isGameFinal, noHitterStatus: awayTeamNoHitterStatus, numPitchers: awayTeamNumPitchers, pitcherName: awayTeamPitcherName, playerTeamName: awayTeamName, playerTeamAbbreviation: awayTeamAbbrv, opposingTeamName: homeTeamName };
        const awayTeamNoHitterHtml = buildNoHitterHtml(awayTeamNoHitterParams);

        const homeBrokenPlay = boxScoreHome.broken_play || brokenEventsByTeam[`${gameId}:${homeTeamId}`];
        const awayBrokenPlay = boxScoreAway.broken_play || brokenEventsByTeam[`${gameId}:${awayTeamId}`];
        const homeBrokenPlayHtml = buildBrokenPlayHtml(homeBrokenPlay);
        const awayBrokenPlayHtml = buildBrokenPlayHtml(awayBrokenPlay);

        const offense = linescore.offense || {};
        const defense = linescore.defense || {};
        const offenseTeamId = offense.team && offense.team.id;
        const defenseTeamId = defense.team && defense.team.id;
        const fallbackBatterTeamAbbrv = isTopInning ? awayTeamAbbrv : homeTeamAbbrv;
        const fallbackPitcherTeamAbbrv = isTopInning ? homeTeamAbbrv : awayTeamAbbrv;
        const batterTeamAbbrv = offenseTeamId === homeTeamId ? homeTeamAbbrv : offenseTeamId === awayTeamId ? awayTeamAbbrv : fallbackBatterTeamAbbrv;
        const pitcherTeamAbbrv = defenseTeamId === homeTeamId ? homeTeamAbbrv : defenseTeamId === awayTeamId ? awayTeamAbbrv : fallbackPitcherTeamAbbrv;
        const currentPitcherName = defense.pitcher && (defense.pitcher.fullName || defense.pitcher.name)
            ? (defense.pitcher.fullName || defense.pitcher.name)
            : 'TBD';
        const currentPitcherStats = defenseTeamId === homeTeamId
            ? homeTeamPitcherStats
            : defenseTeamId === awayTeamId
                ? awayTeamPitcherStats
                : (isTopInning ? homeTeamPitcherStats : awayTeamPitcherStats);
        const currentBatterName = offense.batter && (offense.batter.fullName || offense.batter.name)
            ? (offense.batter.fullName || offense.batter.name)
            : 'TBD';
        const currentBatterStats = offense.batter && offense.batter.stats ? offense.batter.stats : {};
        const batterStatParts = [];
        if (currentBatterStats.hits !== null && currentBatterStats.hits !== undefined &&
            currentBatterStats.atBats !== null && currentBatterStats.atBats !== undefined) {
            batterStatParts.push(`${currentBatterStats.hits} for ${currentBatterStats.atBats}`);
        }
        if (currentBatterStats.avg) {
            batterStatParts.push(`${currentBatterStats.avg} BA`);
        }
        if (currentBatterStats.obp) {
            batterStatParts.push(`${currentBatterStats.obp} OBP`);
        }
        if (currentBatterStats.slg) {
            batterStatParts.push(`${currentBatterStats.slg} SLG`);
        }
        const batterStatsSuffix = batterStatParts.length > 0 ? ` - ${batterStatParts.join(', ')}` : '';
        const matchupInfoHtml = isGameInProgress ? `
                    <div class="matchupInfo">
                        <p class="matchupInfoLine">Pitcher: ${currentPitcherName} (${pitcherTeamAbbrv})${currentPitcherStats ? ` - ${currentPitcherStats}` : ''}</p>
                        <p class="matchupInfoLine">Batter: ${currentBatterName} (${batterTeamAbbrv})${batterStatsSuffix}</p>
                    </div>
                ` : '';

        const basesHtml = isGameInProgress ? buildBasesHtml(isRunnerOnFirst, isRunnerOnSecond, isRunnerOnThird) : '';
        const outsLabel = numOuts === 1 ? 'out' : 'outs';
        const ballsStrikesOutsHtml = isGameInProgress ? `<p class="ballsStrikesOuts"><span class="ballsStrikesLine">${numBalls}-${numStrikes}</span><span class="outsLine">${numOuts} ${outsLabel}</span></p>` : '';
        const inningState = isGameInProgress ? `${isTopInning ? 'Top' : 'Bot'} ${currentInning}` : gameStatusDetailed;
        const metaStatusText = isGameStatusSpecial ? gameStatusDetailed : inningState;
        const showStartTime = !isGameInProgress && !isGameFinal;
        const timeDisplay = (showStartTime && isSelectedDateToday())
            ? `<span class="startTimeTip" data-start-time="${gameData.datetime.dateTime}">${time}</span>`
            : time;
        const gameMetaText = showStartTime ? (isGameStatusSpecial ? `${timeDisplay} - ${metaStatusText}` : timeDisplay) : metaStatusText;
        const brokenPlayHtml = homeBrokenPlayHtml || awayBrokenPlayHtml
            ? `<div class="brokenPlayContainer">${homeBrokenPlayHtml}${awayBrokenPlayHtml}</div>`
            : '';
        const pitcherDetailsHtml = `
                    <details class="pitcherDetails" data-game-id="${gameId}"${openPitcherDetailsGameIds.has(String(gameId)) ? ' open' : ''}>
                        <summary class="pitcherDetailsSummary">Pitching Details</summary>
                        <div class="pitcherDetailsPanel">
                            ${buildPitcherDetailsHtml(homeTeamName, homeTeamAbbrv, homeTeamPitcherLines)}
                            ${buildPitcherDetailsHtml(awayTeamName, awayTeamAbbrv, awayTeamPitcherLines)}
                        </div>
                    </details>
                `;

        const cardHtml = `
            <div id="${gameId}" class="gameContainer ${(homeTeamNoHitterStatus !== 'none' || awayTeamNoHitterStatus !== 'none') ? 'noHitterBackground' : ''}" data-in-progress="${isGameInProgress}" data-final="${isGameFinal}">
                <div class="gameHeadingRow">
                    <h3 class="gameHeading"><span class="awayTeamName">${awayTeamName}</span> @ <span class="homeTeamName">${homeTeamName}</span></h3>
                    <p class="gameMeta${isGameStatusSpecial ? ' redTextColor' : ''}">${gameMetaText}</p>
                </div>

                <div class="gameNoHitterSection">
                    ${homeTeamNoHitterHtml}${awayTeamNoHitterHtml}
                </div>

                <div class="gameDetailsContainer">
                    <table class="gameTable${isDarkMode ? ' gameTableDarkMode' : ''}">
                        <tr class="gameTableHeadRow">
                            <th class="boxScoreFirstCol"></th>
                            ${inningsHeadingHtml}
                            <th>R</th>
                            <th>H</th>
                            <th>E</th>
                        </tr>
                        <tr class="awayTeamTableRow">
                            <th class="boxScoreTeam" scope="row"><span class="boxScoreTeamInner">${teamLogoHtml(awayTeamId)}<span>${awayTeamAbbrv}</span></span></th>
                            ${inningsAwayHtml}
                            <td ${awayTeamRuns > homeTeamRuns ? 'class="bold"' : ''}>${awayTeamRuns}</td>
                            <td>${awayTeamHits}</td>
                            <td>${awayTeamErrors}</td>
                        </tr>
                        <tr class="homeTeamTableRow">
                            <th class="boxScoreTeam" scope="row"><span class="boxScoreTeamInner">${teamLogoHtml(homeTeamId)}<span>${homeTeamAbbrv}</span></span></th>
                            ${inningsHomeHtml}
                            <td ${homeTeamRuns > awayTeamRuns ? 'class="bold"' : ''}>${homeTeamRuns}</td>
                            <td>${homeTeamHits}</td>
                            <td>${homeTeamErrors}</td>
                        </tr>
                    </table>

                    <div class="liveGameInfo">
                        ${basesHtml}
                        ${ballsStrikesOutsHtml}
                    </div>
                </div>
                <div class="gameMatchupSection">${matchupInfoHtml}</div>
                <div class="gameBrokenPlaySection">${brokenPlayHtml}</div>
                ${pitcherDetailsHtml}
            </div>
        `;
        cardHtmlByGameId[String(gameId)] = cardHtml;
        cardOrder.push(String(gameId));
    });

    unfilteredCardHtmlByGameId = cardHtmlByGameId;
    unfilteredCardOrder = cardOrder;
    unfilteredGamesHtml = cardOrder.map(id => cardHtmlByGameId[id]).join('');
    adjustGamesForFavTeam();
    $('#loaderContainer').hide();

    secondsSinceLastUpdated = 0;
    updateLastUpdatedVisibility();
    if (isSelectedDateToday()) {
        setLastUpdated(secondsSinceLastUpdated);
    }
}

function buildNoHitterHtml(teamParams) {
    const isGameFinal = teamParams.isGameFinal;
    const noHitterStatus = teamParams.noHitterStatus;
    const numPitchers = teamParams.numPitchers;
    const pitcherName = teamParams.pitcherName;
    const playerTeamName = teamParams.playerTeamName;
    const playerTeamAbbreviation = teamParams.playerTeamAbbreviation;
    const opposingTeamName = teamParams.opposingTeamName;
    let noHitterHtml = '';

    if (noHitterStatus !== 'none') {
        if (numPitchers === 1) {
            noHitterHtml = `<p>${pitcherName} (${playerTeamAbbreviation}) ${isGameFinal ? 'has thrown' : 'currently has'} a ${noHitterStatus} against the ${opposingTeamName}.</p>`;
        } else {
            noHitterHtml = `<p>The ${playerTeamName} ${isGameFinal ? 'have thrown' : 'currently have'} a ${noHitterStatus} against the ${opposingTeamName}.</p>`;
        }
    }

    return noHitterHtml;
}

function teamLogoHtml(teamId) {
    if (!teamId) return '';
    return `<img class="teamLogo" src="https://www.mlbstatic.com/team-logos/${teamId}.svg" alt="" aria-hidden="true">`;
}

function buildBasesHtml(isRunnerOnFirst, isRunnerOnSecond, isRunnerOnThird) {
    return `
        <div class="bases">
            <div class="rotatedSquare${isDarkMode ? ' rotatedSquareDarkMode' : ''} thirdBase${isRunnerOnThird ? ' grayBackground' : ''}"></div>
            <div class="rotatedSquare${isDarkMode ? ' rotatedSquareDarkMode' : ''} secondBase${isRunnerOnSecond ? ' grayBackground' : ''}"></div>
            <div class="rotatedSquare${isDarkMode ? ' rotatedSquareDarkMode' : ''} firstBase${isRunnerOnFirst ? ' grayBackground' : ''}"></div>
        </div>
    `;
}

function buildPitcherDetailsHtml(teamName, teamAbbrv, pitcherLines) {
    const linesHtml = (pitcherLines || []).map(pitcherLine => {
        const fullName = pitcherLine.full_name || '';
        const statLine = pitcherLine.final_line || pitcherLine.stat_line || '';
        return `<p class="pitcherDetailLine"><span class="pitcherDetailText">${fullName}${statLine ? ` - ${statLine}` : ''}</span></p>`;
    }).join('');

    return `
        <div class="pitcherTeamGroup">
            <p class="pitcherTeamHeading"><span class="pitcherDetailText">${teamName} (${teamAbbrv})</span></p>
            <div class="pitcherLineList">
                ${linesHtml || '<p class="pitcherDetailLine pitcherDetailLineEmpty"><span class="pitcherDetailText">No pitchers recorded.</span></p>'}
            </div>
        </div>
    `;
}

function getTimeUntilStart(utcDateTimeStr) {
    const diffMs = new Date(utcDateTimeStr) - new Date();
    if (diffMs <= 0) return null;
    const diffMins = Math.round(diffMs / 60000);
    if (diffMins < 60) return `${diffMins} ${diffMins === 1 ? 'min' : 'mins'}`;
    const diffHrs = Math.round(diffMins / 60);
    return `${diffHrs} ${diffHrs === 1 ? 'hr' : 'hrs'}`;
}

function getTimeStringFromUTC(dateTimeUTC) {
    const convertedTime = new Date(dateTimeUTC);
    let convertedTimeHours = convertedTime.getHours();
    let convertedTimeMinutes = convertedTime.getMinutes();
    const convertedTimeAmPm = convertedTimeHours < 12 ? 'AM' : 'PM';
    convertedTimeHours = convertedTimeHours > 12 ? convertedTimeHours - 12 : convertedTimeHours;
    convertedTimeHours = convertedTimeHours === 0 ? 12 : convertedTimeHours;
    convertedTimeMinutes = convertedTimeMinutes < 10 ? `0${convertedTimeMinutes}` : convertedTimeMinutes;
    return `${convertedTimeHours}:${convertedTimeMinutes} ${convertedTimeAmPm}`;
}

// Update only the dynamic sections of an existing card, leaving static parts
// (team logos, team names) untouched so <img> elements are never recreated.
function updateCardInPlace($card, newHtml) {
    const $new = $(newHtml);

    // Card-level state — only toggle the class that can change; preserve gameHighlighted etc.
    $card.toggleClass('noHitterBackground', $new.hasClass('noHitterBackground'));
    $card.attr('data-in-progress', $new.attr('data-in-progress'));
    $card.attr('data-final', $new.attr('data-final'));

    // Game status / time line (class may also change for redTextColor)
    const $newMeta = $new.find('.gameMeta');
    $card.find('.gameMeta').attr('class', $newMeta.attr('class')).html($newMeta.html());

    // No-hitter alert banners
    $card.find('.gameNoHitterSection').html($new.find('.gameNoHitterSection').html());

    // Inning heading row (column count grows in extra innings)
    $card.find('.gameTableHeadRow').html($new.find('.gameTableHeadRow').html());

    // Score rows: keep the first cell (team logo + abbrev), replace all score cells after it
    updateTableScoreRow($card.find('.awayTeamTableRow'), $new.find('.awayTeamTableRow'));
    updateTableScoreRow($card.find('.homeTeamTableRow'), $new.find('.homeTeamTableRow'));

    // Bases diagram + balls/strikes/outs
    $card.find('.liveGameInfo').html($new.find('.liveGameInfo').html());

    // Current matchup and broken-play info
    $card.find('.gameMatchupSection').html($new.find('.gameMatchupSection').html());
    $card.find('.gameBrokenPlaySection').html($new.find('.gameBrokenPlaySection').html());

    // Pitcher detail rows (preserve the <details> open/closed state)
    $card.find('.pitcherDetailsPanel').html($new.find('.pitcherDetailsPanel').html());
}

// Replace all cells in a score row except the first (the static logo+name cell).
function updateTableScoreRow($existingRow, $newRow) {
    $existingRow.children().not(':first-child').remove();
    $newRow.children().not(':first-child').each(function() {
        $existingRow.append(this);
    });
}

function adjustGamesForFavTeam() {
    const $container = $('#gamesContainer');

    // Remove cards no longer in this date's game list
    $container.children('.gameContainer').each(function() {
        if (!(String(this.id) in unfilteredCardHtmlByGameId)) {
            $(this).remove();
        }
    });

    // Insert new cards or update existing ones in-place
    unfilteredCardOrder.forEach(gameId => {
        const newHtml = unfilteredCardHtmlByGameId[gameId];
        const $existing = $container.find('#' + gameId);
        if ($existing.length === 0) {
            $container.append(newHtml);
        } else {
            updateCardInPlace($existing, newHtml);
        }
    });

    sortGames();
    initPitcherDetailsState();
    initHighlightState();
    filterGames();
}

// Sort order:
//   0 - favorite team
//   1 - in-progress
//   2 - upcoming (not started / not final)
//   3 - final with completed no-hitter or perfect game
//   4 - all other final games
// Within each tier the original start-time order is preserved (stable sort).
function sortGames() {
    const $gamesContainer = $('#gamesContainer');
    const favoriteTeamValue = $('#favoriteTeam').val();
    const favoriteTeamName = $('#favoriteTeam option:selected').text().toLowerCase();

    const getSortPriority = (el) => {
        const $el = $(el);
        const isInProgress = $el.attr('data-in-progress') === 'true';
        const isFinal = $el.attr('data-final') === 'true';
        const hasNoHitter = $el.hasClass('noHitterBackground');

        if (favoriteTeamValue !== 'none') {
            const home = $el.find('.homeTeamName').text().toLowerCase();
            const away = $el.find('.awayTeamName').text().toLowerCase();
            if (home.includes(favoriteTeamName) || away.includes(favoriteTeamName)) return 0;
        }

        if (isInProgress) return 1;
        if (!isFinal) return 2;
        if (hasNoHitter) return 3;
        return 4;
    };

    const containers = $gamesContainer.children('.gameContainer').toArray();
    containers.sort((a, b) => getSortPriority(a) - getSortPriority(b));
    $gamesContainer.append(containers);
}

function filterGames() {
    const $gameHeadings = $('.gameHeading');
    const filterText = $('#filterGamesInput').val().trim().toLowerCase();

    if ($gameHeadings != null) {
        $gameHeadings.each(function() {
            const homeTeamName = $(this).children('.homeTeamName').text().toLowerCase();
            const awayTeamName = $(this).children('.awayTeamName').text().toLowerCase();
            const $parentGameContainer = $(this).closest('.gameContainer');

            if (homeTeamName.includes(filterText) || awayTeamName.includes(filterText)) {
                $parentGameContainer.show();
            } else {
                $parentGameContainer.hide();
            }
        });
    }
}
