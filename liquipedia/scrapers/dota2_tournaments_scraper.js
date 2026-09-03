import axios from 'axios';
import * as cheerio from 'cheerio';

const USER_AGENT = "MyTestProject/1.0 (myemail@example.com)";

// Dota 2 tournament portal pages
const STATIC_PAGES = [
  "Recent_Tournament_Results",
  "Tier_1_Tournaments",
  "Tier_2_Tournaments",
  "Tier_3_Tournaments",
  "Tier_4_Tournaments",
  "Monthly_Tournaments",
  "Weekly_Tournaments",
  "Show_Matches",
  "National_Tournaments"
];

// Qualifiers are split by year
function buildQualifierUrls(startYear = 2014, endYear = 2026) {
  const urls = [];
  for (let year = startYear; year <= endYear; year++) {
    urls.push(`https://liquipedia.net/dota2/Qualifier_Tournaments/${year}`);
  }
  return urls;
}

function buildAllUrls() {
  const staticUrls = STATIC_PAGES.map(name => `https://liquipedia.net/dota2/${name}`);
  const qualifierUrls = buildQualifierUrls();
  return [...staticUrls, ...qualifierUrls];
}

// Scrape a single Liquipedia tournament listing page
async function scrapePage(url) {
  try {
    const { data } = await axios.get(url, {
      headers: { "User-Agent": USER_AGENT }
    });

    const $ = cheerio.load(data);
    const tournaments = [];

    $('tr.table2__row--body').each((i, el) => {
      const cells = $(el).find('td');

      const tier = $(cells[1]).attr('data-sort-value') || $(cells[1]).text().trim();
      const title = $(el).find('td.column__tournament').text().trim();
      const link = $(el).find('td.column__tournament a').attr('href');
      const date = $(cells[3]).text().trim();
      const prize = $(cells[4]).text().trim();
      const location = $(cells[5]).text().trim().replace(/\s+/g, ' ');
      const participants = $(cells[6]).text().trim();
      const winner = $(cells[7]).text().trim();
      const runnerUp = $(cells[8]).text().trim();

      if (title) {
        tournaments.push({
          sourceUrl: url,
          tier,
          title,
          link: link ? `https://liquipedia.net${link}` : null,
          date,
          prize,
          location,
          participants,
          winner,
          runnerUp
        });
      }
    });

    return tournaments;
  } catch (err) {
    console.log(`Failed to scrape ${url}: ${err.message}`);
    return [];
  }
}

// Scrape every configured Dota 2 tournament page, respecting rate limits
async function getAllTournaments() {
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

export { getAllTournaments, scrapePage, buildAllUrls };