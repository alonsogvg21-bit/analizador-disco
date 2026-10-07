; Instalador de Windows para Analizador de disco (Inno Setup 6).
; No se compila a mano: lo usa build.py, que le pasa los valores con /D:
;   python build.py --instalador

#ifndef Version
  #define Version "0.0.0"
#endif
#ifndef Nombre
  #define Nombre "Analizador de disco"
#endif
#ifndef Ejecutable
  #define Ejecutable "AnalizadorDisco"
#endif
#ifndef Web
  #define Web "https://github.com/alonsogvg21-bit/analizador-disco"
#endif
#ifndef Origen
  #define Origen "..\..\dist\AnalizadorDisco"
#endif
#ifndef Raiz
  #define Raiz "..\.."
#endif
#ifndef Salida
  #define Salida "..\..\dist\entregables"
#endif
#ifndef Archivo
  #define Archivo "AnalizadorDisco-setup"
#endif

[Setup]
; Identificador fijo del producto: no cambiarlo nunca, o las actualizaciones
; se instalarían como un programa distinto.
AppId={{8E1C5B2A-6F3D-4E7A-9B41-2D5C7A9E0F13}
AppName={#Nombre}
AppVersion={#Version}
AppVerName={#Nombre} {#Version}
AppPublisher=alonsogvg21-bit
AppPublisherURL={#Web}
AppSupportURL={#Web}/issues
AppUpdatesURL={#Web}/releases
VersionInfoVersion={#Version}
VersionInfoProductName={#Nombre}
VersionInfoDescription=Instalador de {#Nombre}
DefaultDirName={autopf}\{#Nombre}
DefaultGroupName={#Nombre}
DisableProgramGroupPage=yes
; Se instala solo para el usuario actual y sin pedir permisos de administrador.
; Quien lo prefiera puede elegir "para todos los usuarios" en el propio instalador.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile={#Raiz}\LICENSE
SetupIconFile={#Raiz}\desktop\recursos\icono.ico
UninstallDisplayIcon={app}\{#Ejecutable}.exe
UninstallDisplayName={#Nombre}
OutputDir={#Salida}
OutputBaseFilename={#Archivo}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Si el programa está abierto, el instalador ofrece cerrarlo antes de actualizar.
CloseApplications=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#Origen}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Raiz}\LICENSE"; DestDir: "{app}"; DestName: "LICENCIA.txt"; Flags: ignoreversion
Source: "{#Raiz}\NOTICE"; DestDir: "{app}"; DestName: "LICENCIAS-DE-TERCEROS.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\{#Nombre}"; Filename: "{app}\{#Ejecutable}.exe"
Name: "{group}\Desinstalar {#Nombre}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#Nombre}"; Filename: "{app}\{#Ejecutable}.exe"; Tasks: escritorio

[Run]
Filename: "{app}\{#Ejecutable}.exe"; Description: "{cm:LaunchProgram,{#Nombre}}"; Flags: nowait postinstall skipifsilent

; El desinstalador quita el programa, pero NO el historial, el registro de
; acciones ni las preferencias, que están en %LOCALAPPDATA%\analizador-disco.
; Así no se pierden al actualizar. Se pueden borrar a mano.
