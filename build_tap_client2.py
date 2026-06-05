"""Recompile tap_client to use /var/mobile/tap_sock."""
import subprocess, sys, time, paramiko

TAP_CLIENT_C = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/un.h>

#define SOCK_PATH "/var/mobile/tap_sock"

int main(int argc, char* argv[]) {
    if (argc < 2) { fprintf(stderr, "usage: tap_client tap X Y | swipe X1 Y1 X2 Y2 [STEPS]\n"); return 1; }

    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) { perror("socket"); return 1; }

    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strlcpy(addr.sun_path, SOCK_PATH, sizeof(addr.sun_path));

    if (connect(fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        perror("connect"); close(fd); return 1;
    }

    char buf[256];
    int n = 0;
    if (strcmp(argv[1], "tap") == 0 && argc >= 4)
        n = snprintf(buf, sizeof(buf), "tap %s %s", argv[2], argv[3]);
    else if (strcmp(argv[1], "swipe") == 0 && argc >= 6) {
        const char* steps = argc >= 7 ? argv[6] : "20";
        n = snprintf(buf, sizeof(buf), "swipe %s %s %s %s %s", argv[2], argv[3], argv[4], argv[5], steps);
    } else {
        fprintf(stderr, "unknown command\n"); close(fd); return 1;
    }

    if (write(fd, buf, n) < 0) { perror("write"); close(fd); return 1; }

    char resp[16] = {0};
    read(fd, resp, 15);
    close(fd);
    printf("%s", resp);
    return (strncmp(resp, "ok", 2) == 0) ? 0 : 1;
}
"""

fwd = subprocess.Popen(
    [sys.executable, '-m', 'pymobiledevice3', 'usbmux', 'forward', '2222', '22'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)
time.sleep(2)

try:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect('127.0.0.1', port=2222, username='mobile', password='one', timeout=10)

    def run(cmd, label='', timeout=30):
        _, out, err = c.exec_command(cmd, timeout=timeout)
        o = out.read().decode().strip()
        e = err.read().decode().strip()
        print(f'--- {label} ---')
        if o: print(o)
        if e: print('  err:', e[:300])
        print()
        return o

    sftp = c.open_sftp()
    with sftp.open('/tmp/tap_client2.c', 'w') as f: f.write(TAP_CLIENT_C)
    sftp.close()

    run('echo one | /var/jb/usr/bin/sudo -S -p "" '
        '/var/jb/usr/bin/clang '
        '-isysroot /var/jb/usr/share/SDKs/iPhoneOS.sdk '
        '-o /var/jb/usr/bin/tap_client /tmp/tap_client2.c 2>&1',
        'compile tap_client', timeout=60)
    run('echo one | /var/jb/usr/bin/sudo -S -p "" ldid -S /var/jb/usr/bin/tap_client 2>&1; echo signed:$?', 'sign tap_client')
    run('ls -la /var/jb/usr/bin/tap_client', 'verify')

    c.close()
finally:
    fwd.terminate()
