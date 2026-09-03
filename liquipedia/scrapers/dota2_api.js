import express from 'express';
import fs from 'fs';
import { getAllTournaments } from './dota2_tournaments_scraper.js';
import { getAllPlayers } from './dota2_players_scraper.js';
import { getAllTeams } from './dota2_teams_scraper.js';

const app = express();
const PORT = 3000;

let tournamentCache = [];
let lastTournamentFetch = null;

let playerCache = [];
let lastPlayerFetch = null;

let teamCache = [];
let lastTeamFetch = null;

// ── Home ─────────────────────────────────────────────────────────────────────

app.get('/', (req, res) => {
  res.json({
    message: "Dota 2 API is running",
    cachedTournaments: tournamentCache.length,
    lastTournamentFetch,
    cachedPlayers: playerCache.length,
    lastPlayerFetch,
    cachedTeams: teamCache.length,
    lastTeamFetch
  });
});

// ── Tournament routes (unchanged) ───────────────────────────────────────────

app.get('/fetch', async (req, res) => {
  try {
    tournamentCache = await getAllTournaments();
    lastTournamentFetch = new Date().toISOString();
    fs.writeFileSync('tournaments.json', JSON.stringify(tournamentCache, null, 2));
    res.json({ scraped: tournamentCache.length, lastTournamentFetch });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get('/tournaments', (req, res) => {
  res.json({ count: tournamentCache.length, tournaments: tournamentCache });
});

app.get('/tournaments/tier/:tier', (req, res) => {
  const tier = req.params.tier;
  const results = tournamentCache.filter(t => t.tier === tier);
  res.json({ count: results.length, tournaments: results });
});

app.get('/tournaments/search/:title', (req, res) => {
  const query = req.params.title.toLowerCase();
  const results = tournamentCache.filter(t => t.title.toLowerCase().includes(query));
  res.json({ count: results.length, tournaments: results });
});

app.get('/view', (req, res) => {
  const rows = tournamentCache.map(t => `
    <tr>
      <td>${t.tier}</td>
      <td><a href="${t.link}" target="_blank">${t.title}</a></td>
      <td>${t.date}</td>
      <td>${t.prize}</td>
      <td>${t.location}</td>
      <td>${t.participants}</td>
      <td>${t.winner}</td>
      <td>${t.runnerUp}</td>
    </tr>
  `).join('');

  const html = `
    <html>
    <head>
      <title>Dota 2 Tournaments</title>
      <style>
        body { font-family: sans-serif; margin: 20px; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #ccc; padding: 6px 10px; text-align: left; font-size: 14px; }
        th { background: #222; color: white; position: sticky; top: 0; }
        tr:nth-child(even) { background: #f7f7f7; }
        a { color: #0066cc; text-decoration: none; }
      </style>
    </head>
    <body>
      <h2>Dota 2 Tournaments (${tournamentCache.length} total)</h2>
      <table>
        <thead>
          <tr>
            <th>Tier</th><th>Title</th><th>Date</th><th>Prize</th>
            <th>Location</th><th>Participants</th><th>Winner</th><th>Runner-up</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </body>
    </html>
  `;

  res.send(html);
});

// ── Player routes (new) ─────────────────────────────────────────────────────

app.get('/fetch-players', async (req, res) => {
  try {
    playerCache = await getAllPlayers();
    lastPlayerFetch = new Date().toISOString();
    fs.writeFileSync('players.json', JSON.stringify(playerCache, null, 2));
    res.json({ scraped: playerCache.length, lastPlayerFetch });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get('/players', (req, res) => {
  res.json({ count: playerCache.length, players: playerCache });
});

// Search by ID or name, e.g. /players/search/miracle
app.get('/players/search/:name', (req, res) => {
  const query = req.params.name.toLowerCase();
  const results = playerCache.filter(p =>
    p.id.toLowerCase().includes(query) || (p.name || '').toLowerCase().includes(query)
  );
  res.json({ count: results.length, players: results });
});

// Filter by team, e.g. /players/team/Team%20Spirit
app.get('/players/team/:team', (req, res) => {
  const team = req.params.team;
  const results = playerCache.filter(p => p.team === team);
  res.json({ count: results.length, players: results });
});

app.get('/players/view', (req, res) => {
  const rows = playerCache.map(p => `
    <tr>
      <td>${p.nationality || ''}</td>
      <td><a href="${p.link}" target="_blank">${p.id}</a></td>
      <td>${p.name}</td>
      <td>${p.team}</td>
    </tr>
  `).join('');

  const html = `
    <html>
    <head>
      <title>Dota 2 Players</title>
      <style>
        body { font-family: sans-serif; margin: 20px; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #ccc; padding: 6px 10px; text-align: left; font-size: 14px; }
        th { background: #222; color: white; position: sticky; top: 0; }
        tr:nth-child(even) { background: #f7f7f7; }
        a { color: #0066cc; text-decoration: none; }
      </style>
    </head>
    <body>
      <h2>Dota 2 Players (${playerCache.length} total)</h2>
      <table>
        <thead>
          <tr><th>Flag</th><th>ID</th><th>Name</th><th>Team</th></tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </body>
    </html>
  `;

  res.send(html);
});

// ── Team routes (new) ────────────────────────────────────────────────────────

app.get('/fetch-teams', async (req, res) => {
  try {
    teamCache = await getAllTeams();
    lastTeamFetch = new Date().toISOString();
    fs.writeFileSync('teams.json', JSON.stringify(teamCache, null, 2));
    res.json({ scraped: teamCache.length, lastTeamFetch });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get('/teams', (req, res) => {
  res.json({ count: teamCache.length, teams: teamCache });
});

// Search by name, e.g. /teams/search/spirit
app.get('/teams/search/:name', (req, res) => {
  const query = req.params.name.toLowerCase();
  const results = teamCache.filter(t => t.name.toLowerCase().includes(query));
  res.json({ count: results.length, teams: results });
});

app.get('/teams/view', (req, res) => {
  const rows = teamCache.map(t => `
    <tr>
      <td><a href="${t.link}" target="_blank">${t.name}</a></td>
      <td>${t.region || ''}</td>
    </tr>
  `).join('');

  const html = `
    <html>
    <head>
      <title>Dota 2 Teams</title>
      <style>
        body { font-family: sans-serif; margin: 20px; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #ccc; padding: 6px 10px; text-align: left; font-size: 14px; }
        th { background: #222; color: white; position: sticky; top: 0; }
        tr:nth-child(even) { background: #f7f7f7; }
        a { color: #0066cc; text-decoration: none; }
      </style>
    </head>
    <body>
      <h2>Dota 2 Teams (${teamCache.length} total)</h2>
      <table>
        <thead>
          <tr><th>Name</th><th>Region</th></tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </body>
    </html>
  `;

  res.send(html);
});

// ── Start server ─────────────────────────────────────────────────────────────

app.listen(PORT, () => {
  console.log(`Dota 2 API running at http://localhost:${PORT}`);
  console.log(`Call /fetch for tournaments, /fetch-players for players, /fetch-teams for teams`);
});