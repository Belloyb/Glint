; Media extensions offered by the optional "file associations" installer
; task (included from windows-installer.iss). Kept as a separate include so
; the list is easy to review and extend. Plain [Registry] lines by design:
; a parameterised ISPP macro here compiled on paper but never in practice
; (Inno section parsing rejected the bare macro calls - first real compile,
; v0.12.8). Simple text, nothing to misparse.

; Video containers
Root: HKCU; Subkey: "Software\Classes\.mkv"; ValueType: string; ValueName: ""; ValueData: "Glint.MediaFile"; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\.mp4"; ValueType: string; ValueName: ""; ValueData: "Glint.MediaFile"; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\.m4v"; ValueType: string; ValueName: ""; ValueData: "Glint.MediaFile"; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\.mov"; ValueType: string; ValueName: ""; ValueData: "Glint.MediaFile"; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\.avi"; ValueType: string; ValueName: ""; ValueData: "Glint.MediaFile"; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\.webm"; ValueType: string; ValueName: ""; ValueData: "Glint.MediaFile"; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\.wmv"; ValueType: string; ValueName: ""; ValueData: "Glint.MediaFile"; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\.flv"; ValueType: string; ValueName: ""; ValueData: "Glint.MediaFile"; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\.ts"; ValueType: string; ValueName: ""; ValueData: "Glint.MediaFile"; Flags: uninsdeletevalue; Tasks: fileassoc

; Audio containers/formats
Root: HKCU; Subkey: "Software\Classes\.mp3"; ValueType: string; ValueName: ""; ValueData: "Glint.MediaFile"; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\.flac"; ValueType: string; ValueName: ""; ValueData: "Glint.MediaFile"; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\.ogg"; ValueType: string; ValueName: ""; ValueData: "Glint.MediaFile"; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\.opus"; ValueType: string; ValueName: ""; ValueData: "Glint.MediaFile"; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\.wav"; ValueType: string; ValueName: ""; ValueData: "Glint.MediaFile"; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\.m4a"; ValueType: string; ValueName: ""; ValueData: "Glint.MediaFile"; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\.aac"; ValueType: string; ValueName: ""; ValueData: "Glint.MediaFile"; Flags: uninsdeletevalue; Tasks: fileassoc

; Playlists
Root: HKCU; Subkey: "Software\Classes\.m3u"; ValueType: string; ValueName: ""; ValueData: "Glint.MediaFile"; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\.m3u8"; ValueType: string; ValueName: ""; ValueData: "Glint.MediaFile"; Flags: uninsdeletevalue; Tasks: fileassoc
