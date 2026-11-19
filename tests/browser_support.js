// Chromium instalado con `npx playwright install chromium`, sin rutas del equipo.
const { chromium } = require('playwright');

function launchBrowser() {
  const options = { headless: true };
  const executablePath = process.env.PLAYWRIGHT_EXECUTABLE_PATH || process.env.EDGE_PATH;
  if (executablePath) options.executablePath = executablePath;
  else if (process.env.PLAYWRIGHT_CHANNEL) options.channel = process.env.PLAYWRIGHT_CHANNEL;
  return chromium.launch(options);
}

module.exports = { launchBrowser };
