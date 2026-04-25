const { app, BrowserWindow, session } = require("electron");
const path = require("path");

function setupPermissions() {
  const defaultSession = session.defaultSession;

  defaultSession.setPermissionCheckHandler((webContents, permission) => {
    return permission === "media" || permission === "camera" || permission === "microphone";
  });

  defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    if (permission === "media" || permission === "camera" || permission === "microphone") {
      callback(true);
      return;
    }
    callback(false);
  });
}

function createWindow() {
  const mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    frame: false,
    transparent: false,
    backgroundColor: "#06080f",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  mainWindow.removeMenu();
  mainWindow.loadFile(path.join(__dirname, "index.html"));
}

app.whenReady().then(() => {
  setupPermissions();
  createWindow();
});

app.on("window-all-closed", () => {
  app.quit();
});
