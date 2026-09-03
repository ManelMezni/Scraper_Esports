import axios from 'axios';
import * as cheerio from 'cheerio';

const USER_AGENT = "MyTestProject/1.0 (myemail@example.com)";

// Dota 2 player portal pages, split by region (same pattern as your tournament pages)
const PLAYER_PAGES = [
  "Portal:Players/Americas",
  "Portal:Players/Europe",
  "Portal:Players/China",
  "Portal:Players/Southeast_Asia",
];

function buildAllUrls() {
  return PLAYER_PAGES.map(name => `https://liquipedia.net/dota2/${name}`);
}

/*
 * NOTE: Unlike the tournament table (which uses `tr.table2__row--body`),
 * Liquipedia's player list pages typically render each player as a row
 * inside a `table.wikitable` (or similar), OR inside "player card" divs
 * depending on the page. The selectors below are a best-effort starting
 * point based on Liquipedia's common markup — please confirm them by
 * right-clicking a player row on the live page and inspecting it, the
 * same way you did for the tournament table.
 */
async function scrapePage(url) {
  try {
    const { data } = await axios.get(url, {
      headers: { "User-Agent": USER_AGENT }
    });

    const $ = cheerio.load(data);
    const players = [];

    // Best-effort selector — VERIFY this matches the real row element
    $('table.wikitable tr').each((i, el) => {
      const cells = $(el).find('td');
      if (cells.length === 0) return; // skip header rows

      const id = $(cells[0]).text().trim();               // player handle/ID
      const name = $(cells[1]).text().trim();              // real name
      const nationality = $(cells[0]).find('img').attr('alt') || null; // flag alt text
      const team = $(cells[2]).text().trim();
      const link = $(el).find('a').first().attr('href');

      if (id) {
        players.push({
          sourceUrl: url,
          id,
          name,
          nationality,
          team,
          link: link ? `https://liquipedia.net${link}` : null
        });
      }
    });

    return players;
  } catch (err) {
    console.log(`Failed to scrape ${url}: ${err.message}`);
    return [];
  }
}

// Scrape every configured player page, respecting rate limits
async function getAllPlayers() {
  const urls = buildAllUrls();
  let all = [];

  for (const url of urls) {
    console.log(`Scraping: ${url}`);
    const results = await scrapePage(url);
    all = all.concat(results);

    // Liquipedia terms: max 1 request per 2 seconds
    await new Promise(resolve => setTimeout(resolve, 2000));
  }

  return all;
}

export { getAllPlayers, scrapePage, buildAllUrls }; 