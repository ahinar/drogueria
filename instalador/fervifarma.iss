; =====================================================================
; INSTALADOR DE WINDOWS (Inno Setup) — arma "Fervifarma-Instalador-x.y.z.exe"
; =====================================================================
; PARA QUÉ (para aprender):
;   Toma la carpeta que armó PyInstaller (dist\Fervifarma) y la convierte en
;   un instalador normal de Windows: "Siguiente, Siguiente, Instalar".
;
;   - Se instala SOLO para el usuario de Windows que lo instala, sin pedir
;     permisos de administrador, en:  C:\Users\<usuario>\AppData\Local\Programs\Fervifarma
;   - Crea el ícono en el escritorio y en el menú Inicio.
;   - Opción (marcada): abrir Fervifarma al prender el computador.
;   - Los DATOS (base de datos, fotos, respaldos) quedan en otra carpeta:
;     C:\Users\<usuario>\AppData\Local\Fervifarma  (ver config.py). Ni la
;     actualización ni la desinstalación los borran.
;   - ACTUALIZAR = instalar la versión nueva encima: reemplaza el programa,
;     deja los datos, y al abrir se aplican solos los cambios a la base.
;
;   Se compila con (lo hace GitHub solo, ver .github/workflows/instalador.yml):
;     ISCC.exe /DVersion=1.0.0 instalador\fervifarma.iss
; =====================================================================

#ifndef Version
  #define Version "0.0.0"
#endif

[Setup]
; AppId identifica al programa: NUNCA se cambia (así una versión nueva reemplaza a la anterior)
AppId={{8F4C2A61-3B7D-4E59-9A0C-5D1E7F2B6C34}
AppName=Fervifarma
AppVersion={#Version}
AppVerName=Fervifarma {#Version}
AppPublisher=Fervifarma
DefaultDirName={localappdata}\Programs\Fervifarma
DefaultGroupName=Fervifarma
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Fervifarma-Instalador-{#Version}
SetupIconFile=fervifarma.ico
UninstallDisplayIcon={app}\Fervifarma.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Si el programa está abierto al actualizar, Windows lo cierra para poder reemplazarlo
CloseApplications=force
RestartApplications=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear un ícono en el escritorio"; GroupDescription: "Íconos:"
Name: "alarrancar"; Description: "Abrir Fervifarma al prender el computador"; GroupDescription: "Arranque:"

[Files]
; Todo lo que armó PyInstaller
Source: "..\dist\Fervifarma\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Fervifarma"; Filename: "{app}\Fervifarma.exe"
Name: "{userdesktop}\Fervifarma"; Filename: "{app}\Fervifarma.exe"; Tasks: escritorio
Name: "{userstartup}\Fervifarma"; Filename: "{app}\Fervifarma.exe"; Tasks: alarrancar

[Run]
Filename: "{app}\Fervifarma.exe"; Description: "Abrir Fervifarma ahora"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Solo lo del programa. Los DATOS (en %LOCALAPPDATA%\Fervifarma) NO se borran.
Type: filesandordirs; Name: "{app}"
