; Opsional: Inno Setup 6 (https://jrsoftware.org/isinfo.php). Dijalankan otomatis oleh build_exe.bat bila iscc.exe ada.
; Hasil: Output\DHKRegister_Setup_v1.1.exe  -> memasang aplikasi, PostgreSQL (bila belum ada), database, dan auto-start.
[Setup]
AppName=DHK Register
AppVersion=1.1
DefaultDirName={autopf}\DHKRegister
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputBaseFilename=DHKRegister_Setup_v1.1
Compression=lzma2
SolidCompression=yes
[Files]
Source: "dist\DHKRegister\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install.ps1"" -InstallDir ""{app}"""; StatusMsg: "Memasang PostgreSQL dan menyiapkan database (beberapa menit)..."; Flags: waituntilterminated
[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\uninstall.ps1"""; Flags: waituntilterminated runhidden; RunOnceId: "RemoveTask"
