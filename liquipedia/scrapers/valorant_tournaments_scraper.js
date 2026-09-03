import axios from 'axios';
import * as cheerio from 'cheerio';

const game = "valorant"; 
const qualifierUrls = [];
for (let year = 2014; year <= 2026; year++) {
  qualifierUrls.push(`https://liquipedia.net/${game}/Qualifier_Tournaments/${year}`);
}
// Valorant-specific tournament portal pages
const pageNames = [
  "S-Tier_Tournaments",
  "A-Tier_Tournaments",
  "B-Tier_Tournaments",
  "C-Tier_Tournaments",
  "Miscellaneous_Tournaments",
  "Game_Changers_Tournaments"
];

const urls = [
  ...qualifierUrls,
  ...pageNames.map(name => `https://liquipedia.net/${game}/${name}`)
];

const scrapePage = async (url) => {
  try {
    const { data } = await axios.get(url, {
      headers: {
        "User-Agent": "MyTestProject/1.0 (myemail@example.com)"
      }
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
          game,
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
};

const main = async () => {
  let allTournaments = [];

  for (const url of urls) {
    console.log(`Scraping: ${url}`);
    const results = await scrapePage(url);
    allTournaments = allTournaments.concat(results);

    await new Promise(resolve => setTimeout(resolve, 2000));
  }

  console.log(`\nTotal tournaments found: ${allTournaments.length}`);
  console.table(allTournaments);
};

main();