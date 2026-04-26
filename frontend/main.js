const { app, BrowserWindow, session } = require("electron");
const path = require("path");

function setupPermissions() {
  const defaultSession = session.defaultSession;
  const allowedPermissions = new Set([
    "media",
    "camera",
    "microphone",
    "audio",
    "audioCapture"
  ]);

  defaultSession.setPermissionCheckHandler((webContents, permission) => {
    return allowedPermissions.has(permission);
  });

  defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    if (allowedPermissions.has(permission)) {
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
    titleBarStyle: "hidden",
    transparent: false,
    backgroundColor: "#06080f",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      backgroundThrottling: false
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
