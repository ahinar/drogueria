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
;   - VARIOS COMPUTADORES (desde 1.1.0): una página pregunta cómo se usa este
;     computador (principal que comparte, principal solo, o conectado al
;     principal) y lo guarda en  %LOCALAPPDATA%\Fervifarma\equipo.json
;     (ver config.py). Si es principal que comparte, abre el cortafuegos de
;     Windows solo para la red del local y Tailscale (pide permiso una vez).
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

; =====================================================================
; [Code] = pequeño programa (en lenguaje Pascal) que corre el instalador
; =====================================================================
[Code]
var
  PaginaModo: TInputOptionWizardPage;      // ¿Cómo se usa este computador?
  PaginaServidor: TInputQueryWizardPage;   // Dirección del PC principal (solo para el portátil)

const
  MODO_COMPARTE = 0;   // PC principal que deja conectar al portátil
  MODO_SOLO = 1;       // PC principal, solo este computador (como la versión 1.0)
  MODO_CONECTADO = 2;  // portátil: se conecta al principal
  REGLA = 'Fervifarma';

// ---- 1. Las dos páginas nuevas del asistente ----
procedure InitializeWizard;
var
  Anterior: String;
begin
  PaginaModo := CreateInputOptionPage(wpSelectTasks,
    '¿Cómo se usa este computador?',
    'Fervifarma puede usarse en dos computadores al tiempo, con los mismos datos.',
    'Escoge una opción y dale Siguiente. Si ya tenías el programa, tus datos no se tocan.',
    True, False);
  PaginaModo.Add('PC principal (mostrador) · permitir que otros equipos se conecten');
  PaginaModo.Add('PC principal · solo en este computador');
  PaginaModo.Add('PC conectado (portátil) · trabajar con los datos del PC principal');

  PaginaServidor := CreateInputQueryPage(PaginaModo.ID,
    'Dirección del PC principal',
    '¿A qué computador se conecta este portátil?',
    'Escribe el nombre del PC del mostrador tal como sale en Fervifarma, en ' +
    'Administración → Red y equipos (por ejemplo: mostrador). ' +
    'Antes instala Tailscale en los dos computadores con la misma cuenta.');
  PaginaServidor.Add('Dirección:', False);

  // Lo que se escogió la vez pasada (al actualizar no hay que volver a escribirlo)
  Anterior := GetPreviousData('Modo', '0');
  PaginaModo.SelectedValueIndex := StrToIntDef(Anterior, MODO_COMPARTE);
  PaginaServidor.Values[0] := GetPreviousData('Servidor', '');
end;

// Guardar lo escogido para la próxima actualización
procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'Modo', IntToStr(PaginaModo.SelectedValueIndex));
  SetPreviousData(PreviousDataKey, 'Servidor', PaginaServidor.Values[0]);
end;

// La página de la dirección solo aparece si es el portátil
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = PaginaServidor.ID) and (PaginaModo.SelectedValueIndex <> MODO_CONECTADO);
end;

// No dejar seguir sin dirección
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = PaginaServidor.ID) and (Trim(PaginaServidor.Values[0]) = '') then
  begin
    MsgBox('Escribe la dirección del PC principal (por ejemplo: mostrador).', mbError, MB_OK);
    Result := False;
  end;
end;

// ---- 2. Antes de copiar: cerrar el programa si está abierto ----
// (en el PC principal que comparte, sigue corriendo aunque se cierre la ventana)
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Codigo: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM Fervifarma.exe', '', SW_HIDE, ewWaitUntilTerminated, Codigo);
  Sleep(1000);
  Result := '';
end;

// ---- 3. Después de copiar: escribir equipo.json y abrir el cortafuegos ----
procedure EscribirEquipo;
var
  Carpeta, Servidor, Json: String;
begin
  Carpeta := ExpandConstant('{localappdata}\Fervifarma');
  ForceDirectories(Carpeta);
  Servidor := Trim(PaginaServidor.Values[0]);
  StringChangeEx(Servidor, '"', '', True);     // sin comillas ni barras raras dentro del JSON
  StringChangeEx(Servidor, '\', '', True);
  case PaginaModo.SelectedValueIndex of
    MODO_COMPARTE:  Json := '{"modo": "principal", "compartir": true}';
    MODO_SOLO:      Json := '{"modo": "principal", "compartir": false}';
  else
    Json := '{"modo": "conectado", "servidor": "' + Servidor + '"}';
  end;
  SaveStringToFile(Carpeta + '\equipo.json', Json, False);
end;

procedure AbrirCortafuegos;
var
  Codigo: Integer;
  Orden: String;
begin
  // ¿Ya existe la regla? (preguntar no necesita permisos)
  if Exec(ExpandConstant('{sys}\netsh.exe'), 'advfirewall firewall show rule name="' + REGLA + '"',
          '', SW_HIDE, ewWaitUntilTerminated, Codigo) and (Codigo = 0) then
    Exit;
  // Crearla sí necesita permiso de administrador: Windows pregunta (UAC) una sola vez.
  // Solo deja entrar al programa, por el puerto 8765, desde la red del local y Tailscale.
  Orden := 'advfirewall firewall add rule name="' + REGLA + '" dir=in action=allow protocol=TCP localport=8765 ' +
           'program="' + ExpandConstant('{app}\Fervifarma.exe') + '" ' +
           'remoteip=localsubnet,100.64.0.0/10,fd7a:115c:a1e0::/48 profile=any';
  if not ShellExec('runas', ExpandConstant('{sys}\netsh.exe'), Orden, '', SW_HIDE, ewWaitUntilTerminated, Codigo) then
    MsgBox('No se pudo abrir el cortafuegos de Windows para el portátil.' + #13#10 +
           'Vuelve a correr el instalador y, cuando Windows pregunte, dale Sí.', mbInformation, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    EscribirEquipo;
    if PaginaModo.SelectedValueIndex = MODO_COMPARTE then
      AbrirCortafuegos;
  end;
end;
