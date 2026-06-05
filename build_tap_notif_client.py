"""Build tap_client that communicates with backboardd hook via Darwin notification.
Writes /tmp/tap_cmd, posts 'com.lab.hid.cmd', polls /tmp/tap_resp.
No Unix socket needed.
"""
import subprocess, sys, time, paramiko

TAP_CLIENT_C = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <sys/stat.h>
#include <notify.h>

#define CMD_PATH  "/tmp/tap_cmd"
#define RESP_PATH "/tmp/tap_resp"

static int send_cmd(const char* cmd) {
    // Remove stale response
    unlink(RESP_PATH);

    // Write command
    FILE* f = fopen(CMD_PATH, "w");
    if (!f) { fprintf(stderr, "fopen(%s): %s\n", CMD_PATH, strerror(errno)); return 1; }
    fputs(cmd, f);
    fclose(f);

    // Post notification to backboardd hook
    uint32_t st = notify_post("com.lab.hid.cmd");
    if (st != NOTIFY_STATUS_OK) {
        fprintf(stderr, "notify_post failed: %u\n", st);
        return 1;
    }

    // Poll for response (up to 3 seconds)
    for (int i = 0; i < 60; i++) {
        usleep(50000);  // 50ms
        struct stat sb;
        if (stat(RESP_PATH, &sb) == 0 && sb.st_size > 0) {
            FILE* rf = fopen(RESP_PATH, "r");
            if (rf) {
                char resp[16] = {0};
                fgets(resp, 15, rf);
                fclose(rf);
                printf("%s", resp);
                return (strncmp(resp, "ok", 2) == 0) ? 0 : 1;
            }
        }
    }
    fprintf(stderr, "timeout waiting for response\n");
    return 1;
}

int main(int argc, char* argv[]) {
    if (argc < 2) {
        fprintf(stderr, "usage: tap_client tap X Y | swipe X1 Y1 X2 Y2 [STEPS]\n");
        return 1;
    }

    char buf[256];
    if (strcmp(argv[1], "tap") == 0 && argc >= 4) {
        snprintf(buf, sizeof(buf), "tap %s %s", argv[2], argv[3]);
    } else if (strcmp(argv[1], "swipe") == 0 && argc >= 6) {
        const char* steps = argc >= 7 ? argv[6] : "20";
        snprintf(buf, sizeof(buf), "swipe %s %s %s %s %s",
                 argv[2], argv[3], argv[4], argv[5], steps);
    } else {
        fprintf(stderr, "unknown command\n");
        return 1;
    }

    return send_cmd(buf);
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

    def run(cmd, label='', timeout=60):
        _, out, err = c.exec_command(cmd, timeout=timeout)
        o = out.read().decode().strip()
        e = err.read().decode().strip()
        print(f'--- {label} ---')
        if o: print(o)
        if e: print('  err:', e[:400])
        print()
        return o

    sftp = c.open_sftp()
    with sftp.open('/tmp/tap_notif_client.c', 'w') as f: f.write(TAP_CLIENT_C)
    sftp.close()

    run('echo one | /var/jb/usr/bin/sudo -S -p "" '
        '/var/jb/usr/bin/clang '
        '-isysroot /var/jb/usr/share/SDKs/iPhoneOS.sdk '
        '-Wl,-undefined,dynamic_lookup '
        '-o /var/jb/usr/bin/tap_client /tmp/tap_notif_client.c 2>&1',
        'compile tap_client', timeout=60)

    run('echo one | /var/jb/usr/bin/sudo -S -p "" ldid -S /var/jb/usr/bin/tap_client; echo signed:$?',
        'sign tap_client')
    run('ls -la /var/jb/usr/bin/tap_client', 'verify')

    # Quick test (backboardd hook must still be injected from previous run)
    run('cat /tmp/taphook.log 2>&1 | tail -5', 'current hook log')

    pid_out = run('ps -A | grep backboardd | grep -v grep', 'backboardd pid')
    bb_pid = None
    for line in pid_out.splitlines():
        parts = line.split()
        if parts:
            try: bb_pid = int(parts[0]); break
            except ValueError: pass
    print(f'backboardd PID: {bb_pid}')

    if bb_pid:
        print('>>> WATCH SCREEN - tap test via notify pipeline <<<')
        run('/var/jb/usr/bin/tap_client tap 187 333; echo exit:$?', 'tap test', timeout=10)
        time.sleep(1)
        run('cat /tmp/taphook.log 2>&1 | tail -10', 'log after tap')

        print('>>> WATCH SCREEN - swipe up test <<<')
        run('/var/jb/usr/bin/tap_client swipe 187 500 187 200 20; echo exit:$?', 'swipe test', timeout=12)
        time.sleep(1)
        run('cat /tmp/taphook.log 2>&1 | tail -10', 'log after swipe')
    else:
        print('backboardd not running â€” re-inject first')

    c.close()
finally:
    fwd.terminate()
