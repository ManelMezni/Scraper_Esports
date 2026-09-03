import axios from 'axios';
import * as cheerio from 'cheerio';

const USER_AGENT = "MyTestProject/1.0 (myemail@example.com)";

// Dota 2 team portal pages, split by region (same pattern as tournaments/players)
const TEAM_PAGES = [
  "Portal:Teams/Americas",
  "Portal:Teams/Europe",
  "Portal:Teams/China",
  "Portal:Teams/Southeast_Asia",
];

function buildAllUrls() {
  return TEAM_PAGES.map(name => `https://liquipedia.net/dota2/${name}`);
}

/*
 * NOTE: Liquipedia team lists are usually rendered as "TeamCard" blocks
 * (div-based), not a plain <table>, which is different from both the
 * tournament table and (possibly) the player table. The selectors below
 * are a best-effort starting point — please verify by inspecting a real
 * team card on the live page before trusting the output, the same way
 * you did for the tournament table.
 */
async function scrapePage(url) {
  try {
    const { data } = await axios.get(url, {
      headers: { "User-Agent": USER_AGENT }
    });

    const $ = cheerio.load(data);
    const teams = [];

    // Real structure: each region section is a div.template-box containing
    // a table.wikitable, with team rows as <tr> (first row is a <th> header)
    $('.template-box table.wikitable tr').each((i, el) => {
      const headerCell = $(el).find('th');
      if (headerCell.length > 0) return; // skip header row

      const cells = $(el).find('td');
      if (cells.length === 0) return;

      const link = $(el).find('a').first().attr('href');
      const name = $(el).find('a').first().text().trim() || $(cells[0]).text().trim();

      if (name) {
        teams.push({
          sourceUrl: url,
          name,
          link: link ? `https://liquipedia.net${link}` : null
        });
      }
    });

    return teams;
  } catch (err) {
    console.log(`Failed to scrape ${url}: ${err.message}`);
    return [];
  }
}

// Scrape every configured team page, respecting rate limits
async function getAllTeams() {
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

export { getAllTeams, scrapePage, buildAllUrls };