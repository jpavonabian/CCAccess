$ErrorActionPreference = 'Stop'
python -m PyInstaller --noconfirm --clean --windowed --name CCAccess `
  --hidden-import keyring.backends.Windows `
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets `
  --exclude-module PySide6.QtPdf --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQml `
  --exclude-module PySide6.Qt3DCore --exclude-module PySide6.QtCharts --exclude-module PySide6.QtMultimedia `
  --exclude-module PySide6.QtSql --exclude-module PySide6.QtNetwork `
  run_ccaccess.py
Write-Host "Listo: dist\CCAccess\CCAccess.exe"
