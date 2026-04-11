#!/bin/bash
# VPS Security Audit Script
# Run with: sudo bash sec_audit.sh

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================"
echo "  VPS SECURITY AUDIT"
echo "  Generated: $(date)"
echo "========================================"
echo ""

# 1. System Info
echo -e "${YELLOW}[1] System Information${NC}"
echo "OS: $(cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"')"
echo "Kernel: $(uname -r)"
echo "Hostname: $(hostname)"
echo "Uptime: $(uptime -p 2>/dev/null || uptime)"
echo ""

# 2. SSH Security
echo -e "${YELLOW}[2] SSH Configuration${NC}"
if [ -f /etc/ssh/sshd_config ]; then
    ROOT_LOGIN=$(grep -E "^PermitRootLogin" /etc/ssh/sshd_config | awk '{print $2}')
    PASS_AUTH=$(grep -E "^PasswordAuthentication" /etc/ssh/sshd_config | awk '{print $2}')
    PUBKEY_AUTH=$(grep -E "^PubkeyAuthentication" /etc/ssh/sshd_config | awk '{print $2}')
    SSH_PORT=$(grep -E "^Port" /etc/ssh/sshd_config | awk '{print $2}')
    
    echo "SSH Port: ${SSH_PORT:-22}"
    echo -e "Root Login: ${ROOT_LOGIN:-prohibit-password} ${NC}"
    echo -e "Password Auth: ${PASS_AUTH:-yes} ${NC}"
    echo "Pubkey Auth: ${PUBKEY_AUTH:-yes}"
    
    # Warnings
    if [ "$ROOT_LOGIN" = "yes" ]; then
        echo -e "${RED}  ⚠ WARNING: Root login with password enabled!${NC}"
    fi
    if [ "$PASS_AUTH" = "yes" ]; then
        echo -e "${YELLOW}  ⚠ NOTICE: Password authentication enabled (keys recommended)${NC}"
    fi
else
    echo "SSH config not found!"
fi
echo ""

# 3. Firewall Status
echo -e "${YELLOW}[3] Firewall Status${NC}"
if command -v ufw &> /dev/null; then
    ufw_status=$(ufw status 2>/dev/null | head -1)
    echo "UFW: $ufw_status"
    if echo "$ufw_status" | grep -q "inactive"; then
        echo -e "${RED}  ⚠ WARNING: UFW is inactive!${NC}"
    fi
    echo "" && echo "UFW Rules:"
    ufw status verbose 2>/dev/null | tail -n +4
elif command -v iptables &> /dev/null; then
    echo "iptables rules:"
    iptables -L -n 2>/dev/null | head -5
else
    echo -e "${RED}  ⚠ WARNING: No firewall detected!${NC}"
fi
echo ""

# 4. Open Ports
echo -e "${YELLOW}[4] Open Network Ports${NC}"
ss -tlnp 2>/dev/null | grep LISTEN || netstat -tlnp 2>/dev/null | grep LISTEN
echo ""

# 5. User Accounts
echo -e "${YELLOW}[5] User Accounts${NC}"
echo "Users with shell access:"
awk -F: '$7 ~ /bash|sh/ {print "  - " $1}' /etc/passwd
echo ""
echo "Sudo group members:"
getent group sudo 2>/dev/null | cut -d: -f4 | tr ',' '\n' | sed 's/^/  - /'
echo ""

# 6. Authentication Logs
echo -e "${YELLOW}[6] Recent Authentication Events${NC}"
echo "Failed SSH attempts (last 24h):"
if command -v journalctl &> /dev/null; then
    count=$(journalctl -u sshd --since "24 hours ago" 2>/dev/null | grep -c "Failed password" || echo 0)
    echo "  Count: $count"
    if [ "$count" -gt 10 ]; then
        echo -e "${RED}  ⚠ WARNING: High number of failed attempts!${NC}"
    fi
else
    echo "  (journalctl not available)"
fi
echo "" && echo "Last successful logins:"
last -i | head -5 | sed 's/^/  /'
echo ""

# 7. Running Services
echo -e "${YELLOW}[7] Running Services${NC}"
echo "Total services: $(systemctl list-units --type=service --state=running 2>/dev/null | grep -c running || echo N/A)"
echo "" && echo "Exposed services (listening on 0.0.0.0 or :::):"
ss -tlnp 2>/dev/null | grep -E "0.0.0.0|:::" | sed 's/^/  /'
echo ""

# 8. Auto-updates
echo -e "${YELLOW}[8] Automatic Updates${NC}"
if dpkg -l | grep -q unattended-upgrades; then
    echo "unattended-upgrades: installed"
    if systemctl is-active unattended-upgrades &> /dev/null; then
        echo -e "${GREEN}  ✓ Auto-updates enabled${NC}"
    else
        echo -e "${YELLOW}  ⚠ Installed but not running${NC}"
    fi
else
    echo -e "${YELLOW}  ⚠ WARNING: unattended-upgrades not installed${NC}"
fi
echo ""

# 9. System Resources
echo -e "${YELLOW}[9] System Resources${NC}"
echo "Disk usage:"
df -h / | tail -1 | awk '{print "  Used: " $3 " / " $2 " (" $5 ")"}'
if command -v free &> /dev/null; then
    echo "" && echo "Memory:"
    free -h | grep Mem | awk '{print "  Used: " $3 " / " $2}'
fi
echo ""

# 10. Critical File Permissions
echo -e "${YELLOW}[10] Critical File Permissions${NC}"
echo "Checking /etc/shadow permissions..."
SHADOW_PERMS=$(stat -c "%a" /etc/shadow 2>/dev/null || stat -f "%OLp" /etc/shadow 2>/dev/null)
if [ "$SHADOW_PERMS" = "0" ] || [ "$SHADOW_PERMS" = "640" ]; then
    echo -e "${GREEN}  ✓ /etc/shadow permissions OK ($SHADOW_PERMS)${NC}"
else
    echo -e "${YELLOW}  /etc/shadow permissions: $SHADOW_PERMS${NC}"
fi
echo ""

# 11. Cron Jobs
echo -e "${YELLOW}[11] Cron Jobs${NC}"
echo "System crontab:"
ls -la /etc/cron.d/ 2>/dev/null | tail -n +2 | sed 's/^/  /'
echo "" && echo "User crontabs:"
for user in $(cut -f1 -d: /etc/passwd | head -20); do
    crontab -u $user -l 2>/dev/null | grep -v "^#" | grep -q . && echo "  $user: [has crontab]"
done
echo ""

# 12. Listening Processes Summary
echo -e "${YELLOW}[12] Security Summary${NC}"
echo "Active internet-facing services:"
ss -tlnp 2>/dev/null | grep LISTEN | wc -l | xargs -I {} echo "  {} listening sockets"
echo ""

# Recommendations
echo -e "${YELLOW}================ SECURITY RECOMMENDATIONS ================${NC}"

if [ "$PASS_AUTH" = "yes" ]; then
    echo -e "${YELLOW}• Disable password auth, use SSH keys only:${NC}"
    echo "  sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config"
fi

if echo "$ufw_status" 2>/dev/null | grep -q "inactive"; then
    echo -e "${YELLOW}• Enable firewall:${NC}"
    echo "  ufw enable"
fi

if ! dpkg -l | grep -q fail2ban 2>/dev/null; then
    echo -e "${YELLOW}• Install fail2ban for brute-force protection:${NC}"
    echo "  apt install fail2ban"
fi

if ! dpkg -l | grep -q unattended-upgrades 2>/dev/null; then
    echo -e "${YELLOW}• Enable automatic security updates:${NC}"
    echo "  apt install unattended-upgrades"
fi

echo -e "${GREEN}• Restart SSH after config changes:${NC}"
echo "  systemctl restart sshd"
echo ""

echo "Audit complete at $(date)"
