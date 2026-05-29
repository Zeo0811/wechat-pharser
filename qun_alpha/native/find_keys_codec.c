/*
 * find_keys_codec.c — 实验性：codec_ctx 方式提取微信 4.1 数据库密钥（免 SIP）
 *
 * 原理：微信 4.1 内存里不再保留 x'<hex>' 字符串，但打开 DB 后 SQLCipher 的
 * codec_ctx 仍持有 16 字节 salt 与 32 字节派生 enc_key。本工具：
 *   1. 读每个 .db 的 salt(前16字节) + page1(4096) 用于校验
 *   2. 扫微信进程内存，找每个 salt 的 16 字节原始字节
 *   3. 在每个命中点 ±WINDOW 字节内滑动取 32 字节候选 enc_key
 *   4. 用 page1 HMAC 校验（mac_key=PBKDF2-HMAC-SHA512(key, salt^0x3a, 2, 32)，
 *      HMAC-SHA512(mac_key, page1[16:4032]||LE32(1)) == page1[4032:4096]）
 *   5. 命中即该库 enc_key；并用该候选去试所有未解库（多库常共用同一 key）
 *
 * 前置：微信 ad-hoc 重签名（不需关 SIP）、微信开着且已登录、以 root 运行
 * 编译：cc -O2 -o find_keys_codec find_keys_codec.c -framework Foundation
 * 运行：sudo ./find_keys_codec [pid] [window_bytes]
 * 输出：./all_keys.json（兼容 decrypt_db.py）+ 诊断信息到 stderr
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <dirent.h>
#include <ftw.h>
#include <pwd.h>
#include <sys/stat.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <CommonCrypto/CommonKeyDerivation.h>
#include <CommonCrypto/CommonHMAC.h>
#include <CommonCrypto/CommonCryptor.h>

#define MAX_DBS 512
#define SALT_SIZE 16
#define KEY_SIZE 32
#define PAGE_SZ 4096
#define RESERVE_SZ 80
#define HMAC_SZ 64
#define CHUNK_SIZE (16 * 1024 * 1024)
#define DEFAULT_WINDOW (8 * 1024 * 1024)   /* 命中点前后各扫多少字节 */

typedef struct {
    char rel[256];
    unsigned char salt[SALT_SIZE];
    unsigned char page1[PAGE_SZ];
    int has_page1;
    int solved;
    char enc_key_hex[65];
    long salt_hits;
} db_t;

static db_t g_db[MAX_DBS];
static int g_db_count = 0;

/* 读 DB 的 salt(16) 与 page1(4096)。已是明文 SQLite 的跳过。返回 0 成功 */
static int load_db(const char *path, db_t *out) {
    FILE *f = fopen(path, "rb");
    if (!f) return -1;
    size_t n = fread(out->page1, 1, PAGE_SZ, f);
    fclose(f);
    if (n < PAGE_SZ) return -1;
    if (memcmp(out->page1, "SQLite format 3", 15) == 0) return -1; /* 未加密 */
    memcpy(out->salt, out->page1, SALT_SIZE);
    out->has_page1 = 1;
    out->solved = 0;
    out->salt_hits = 0;
    out->enc_key_hex[0] = '\0';
    return 0;
}

static int nftw_collect(const char *fpath, const struct stat *sb,
                        int typeflag, struct FTW *ftwbuf) {
    (void)sb; (void)ftwbuf;
    if (typeflag != FTW_F) return 0;
    size_t len = strlen(fpath);
    if (len < 3 || strcmp(fpath + len - 3, ".db") != 0) return 0;
    if (g_db_count >= MAX_DBS) return 0;
    db_t tmp;
    if (load_db(fpath, &tmp) != 0) return 0;
    const char *rel = strstr(fpath, "db_storage/");
    if (rel) rel += strlen("db_storage/");
    else { rel = strrchr(fpath, '/'); rel = rel ? rel + 1 : fpath; }
    strncpy(tmp.rel, rel, 255); tmp.rel[255] = '\0';
    g_db[g_db_count] = tmp;
    g_db_count++;
    return 0;
}

static pid_t find_wechat_pid(void) {
    FILE *fp = popen("pgrep -x WeChat", "r");
    if (!fp) return -1;
    char buf[64]; pid_t pid = -1;
    if (fgets(buf, sizeof(buf), fp)) pid = atoi(buf);
    pclose(fp);
    return pid;
}

/* 极快预筛：用候选 key AES 解 page1 第一个密文块，验 SQLite 头固定字节。
 * 解密块对应页偏移 16..31：off16-17=页大小0x1000, off20=reserve0x50, 21-23=0x40,0x20,0x20。
 * 命中概率 ~1/2^48，几乎等于正确密钥；用来在大窗口里廉价排除海量候选。 */
static int cheap_aes_ok(const unsigned char *cand, const db_t *db) {
    unsigned char dec[16]; size_t moved = 0;
    if (CCCrypt(kCCDecrypt, kCCAlgorithmAES, kCCOptionECBMode,
                cand, KEY_SIZE, NULL,
                db->page1 + SALT_SIZE, 16, dec, 16, &moved) != 0) return 0;
    const unsigned char *iv = db->page1 + (PAGE_SZ - RESERVE_SZ); /* 4016 */
    for (int i = 0; i < 16; i++) dec[i] ^= iv[i];
    return dec[0] == 0x10 && dec[1] == 0x00 &&
           dec[4] == 0x50 && dec[5] == 0x40 && dec[6] == 0x20 && dec[7] == 0x20;
}

/* 完整 HMAC 校验（贵，只在预筛通过后跑）。返回 1 = 正确 */
static int hmac_ok(const unsigned char *cand, const db_t *db) {
    unsigned char mac_salt[SALT_SIZE];
    for (int i = 0; i < SALT_SIZE; i++) mac_salt[i] = db->salt[i] ^ 0x3a;
    unsigned char mac_key[KEY_SIZE];
    if (CCKeyDerivationPBKDF(kCCPBKDF2, (const char *)cand, KEY_SIZE,
                             mac_salt, SALT_SIZE,
                             kCCPRFHmacAlgSHA512, 2,
                             mac_key, KEY_SIZE) != 0)  /* kCCSuccess==0 */
        return 0;
    const unsigned char *hmac_data = db->page1 + SALT_SIZE;
    size_t hmac_len = PAGE_SZ - RESERVE_SZ + 16 - SALT_SIZE; /* 4016 */
    unsigned char pgno[4] = {1, 0, 0, 0};
    CCHmacContext ctx;
    CCHmacInit(&ctx, kCCHmacAlgSHA512, mac_key, KEY_SIZE);
    CCHmacUpdate(&ctx, hmac_data, hmac_len);
    CCHmacUpdate(&ctx, pgno, 4);
    unsigned char out[HMAC_SZ];
    CCHmacFinal(&ctx, out);
    return memcmp(out, db->page1 + PAGE_SZ - HMAC_SZ, HMAC_SZ) == 0;
}

/* 用候选 32 字节 key 校验某 DB 的 page1（窗口轮用）。返回 1 = 正确 */
static int verify_key(const unsigned char *cand, const db_t *db) {
    if (!cheap_aes_ok(cand, db)) return 0;   /* 廉价预筛, 绝大多数候选在此被拒 */
    return hmac_ok(cand, db);
}

static void to_hex(const unsigned char *b, int n, char *out) {
    for (int i = 0; i < n; i++) sprintf(out + i * 2, "%02x", b[i]);
    out[n * 2] = '\0';
}

/* 用一个已验证的候选 key 去试所有未解库（多库常共用同一 key） */
static void propagate(const unsigned char *cand) {
    for (int d = 0; d < g_db_count; d++) {
        if (g_db[d].solved) continue;
        if (verify_key(cand, &g_db[d])) {
            g_db[d].solved = 1;
            to_hex(cand, KEY_SIZE, g_db[d].enc_key_hex);
        }
    }
}

static int all_solved(void) {
    for (int d = 0; d < g_db_count; d++) if (!g_db[d].solved) return 0;
    return 1;
}

int main(int argc, char *argv[]) {
    pid_t pid = (argc >= 2) ? atoi(argv[1]) : find_wechat_pid();
    long window = (argc >= 3) ? atol(argv[2]) : DEFAULT_WINDOW;
    if (pid <= 0) { fprintf(stderr, "WeChat 未运行\n"); return 1; }

    fprintf(stderr, "=== find_keys_codec (实验性, 免SIP, 4.1) ===\n");
    fprintf(stderr, "WeChat PID: %d, window=±%ld 字节\n", pid, window);

    mach_port_t task;
    if (task_for_pid(mach_task_self(), pid, &task) != KERN_SUCCESS) {
        fprintf(stderr, "task_for_pid 失败：需 root + 微信已 ad-hoc 重签名\n");
        return 1;
    }

    const char *home = getenv("HOME");
    const char *su = getenv("SUDO_USER");
    if (su) { struct passwd *pw = getpwnam(su); if (pw && pw->pw_dir) home = pw->pw_dir; }
    if (!home) home = "/root";

    char base[512];
    snprintf(base, sizeof(base),
        "%s/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files", home);
    DIR *xdir = opendir(base);
    if (xdir) {
        struct dirent *ent;
        while ((ent = readdir(xdir)) != NULL) {
            if (ent->d_name[0] == '.') continue;
            char sp[768];
            snprintf(sp, sizeof(sp), "%s/%s/db_storage", base, ent->d_name);
            struct stat st;
            if (stat(sp, &st) == 0 && S_ISDIR(st.st_mode))
                nftw(sp, nftw_collect, 20, FTW_PHYS);
        }
        closedir(xdir);
    }
    fprintf(stderr, "加密 DB 数：%d\n", g_db_count);
    if (g_db_count == 0) { fprintf(stderr, "没找到加密 DB\n"); return 1; }

    long total_scanned = 0, candidates_tried = 0;
    mach_vm_address_t addr = 0;
    while (!all_solved()) {
        mach_vm_size_t size = 0;
        vm_region_basic_info_data_64_t info;
        mach_msg_type_number_t icount = VM_REGION_BASIC_INFO_COUNT_64;
        mach_port_t obj;
        if (mach_vm_region(task, &addr, &size, VM_REGION_BASIC_INFO_64,
                           (vm_region_info_t)&info, &icount, &obj) != KERN_SUCCESS)
            break;
        if (size == 0) { addr++; continue; }

        if (info.protection & VM_PROT_READ) {
            mach_vm_address_t ca = addr;
            while (ca < addr + size) {
                mach_vm_size_t cs = addr + size - ca;
                if (cs > CHUNK_SIZE) cs = CHUNK_SIZE;
                vm_offset_t data; mach_msg_type_number_t dc;
                if (mach_vm_read(task, ca, cs, &data, &dc) == KERN_SUCCESS) {
                    unsigned char *buf = (unsigned char *)data;
                    total_scanned += dc;
                    /* 对每个未解库，找它的 salt，命中后在窗口内试候选 */
                    for (int d = 0; d < g_db_count; d++) {
                        if (g_db[d].solved) continue;
                        unsigned char *p = buf;
                        size_t remain = dc;
                        while (remain >= SALT_SIZE) {
                            unsigned char *hit = memmem(p, remain, g_db[d].salt, SALT_SIZE);
                            if (!hit) break;
                            g_db[d].salt_hits++;
                            /* 窗口 [hit-window, hit+window] 内滑动 32 字节候选, 步长 4 */
                            long lo = (hit - buf) - window; if (lo < 0) lo = 0;
                            long hi = (hit - buf) + window;
                            if ((mach_vm_size_t)(hi + KEY_SIZE) > dc) hi = dc - KEY_SIZE;
                            for (long off = lo; off <= hi && !g_db[d].solved; off += 8) {
                                candidates_tried++;
                                if (verify_key(buf + off, &g_db[d])) {
                                    propagate(buf + off);  /* 解了它+共用此 key 的库 */
                                }
                            }
                            p = hit + SALT_SIZE;
                            remain = dc - (p - buf);
                        }
                    }
                    mach_vm_deallocate(mach_task_self(), data, dc);
                }
                if (cs > window * 2) ca += cs - SALT_SIZE; else ca += cs;
            }
        }
        addr += size;
    }

    /* ===== 第二轮：全读写堆扫描（不限窗口），抓 key 离 salt 远的库 ===== */
    if (!all_solved()) {
        int rem = 0;
        for (int d = 0; d < g_db_count; d++)
            if (!g_db[d].solved && g_db[d].salt_hits > 0) rem++;
        fprintf(stderr, "\n[第二轮] 全读写堆扫描剩余 %d 个 active 库 (key 离 salt 远的)...\n", rem);
        long cand2 = 0;
        addr = 0;
        while (!all_solved()) {
            mach_vm_size_t size = 0;
            vm_region_basic_info_data_64_t info;
            mach_msg_type_number_t icount = VM_REGION_BASIC_INFO_COUNT_64;
            mach_port_t obj;
            if (mach_vm_region(task, &addr, &size, VM_REGION_BASIC_INFO_64,
                               (vm_region_info_t)&info, &icount, &obj) != KERN_SUCCESS)
                break;
            if (size == 0) { addr++; continue; }
            /* 只扫可写堆区（key 缓冲在堆上）*/
            if ((info.protection & (VM_PROT_READ | VM_PROT_WRITE)) ==
                (VM_PROT_READ | VM_PROT_WRITE)) {
                mach_vm_address_t ca = addr;
                while (ca < addr + size) {
                    mach_vm_size_t cs = addr + size - ca;
                    if (cs > CHUNK_SIZE) cs = CHUNK_SIZE;
                    vm_offset_t data; mach_msg_type_number_t dc;
                    if (mach_vm_read(task, ca, cs, &data, &dc) == KERN_SUCCESS) {
                        unsigned char *buf = (unsigned char *)data;
                        unsigned char ctxbuf[kCCContextSizeAES128 + 64];
                        for (long off = 0; off + KEY_SIZE <= (long)dc && !all_solved(); off += 16) {
                            const unsigned char *cand = buf + off;
                            cand2++;
                            /* 每候选只建一次 cryptor（栈上免 malloc），对各未解库复用解块预筛 */
                            CCCryptorRef cr; size_t used;
                            if (CCCryptorCreateFromData(kCCDecrypt, kCCAlgorithmAES,
                                    kCCOptionECBMode, cand, KEY_SIZE, NULL,
                                    ctxbuf, sizeof(ctxbuf), &cr, &used) != 0)
                                continue;
                            for (int d = 0; d < g_db_count; d++) {
                                if (g_db[d].solved || g_db[d].salt_hits == 0) continue;
                                unsigned char dec[16]; size_t moved = 0;
                                CCCryptorUpdate(cr, g_db[d].page1 + SALT_SIZE, 16,
                                                dec, 16, &moved);
                                const unsigned char *iv = g_db[d].page1 + (PAGE_SZ - RESERVE_SZ);
                                if ((dec[0]^iv[0])==0x10 && (dec[1]^iv[1])==0x00 &&
                                    (dec[4]^iv[4])==0x50 && (dec[5]^iv[5])==0x40 &&
                                    (dec[6]^iv[6])==0x20 && (dec[7]^iv[7])==0x20) {
                                    if (hmac_ok(cand, &g_db[d])) propagate(cand);
                                }
                            }
                            CCCryptorRelease(cr);
                        }
                        mach_vm_deallocate(mach_task_self(), data, dc);
                    }
                    ca += cs;
                }
            }
            addr += size;
        }
        fprintf(stderr, "[第二轮] 试候选 %ld 个\n", cand2);
    }

    int solved = 0; long total_hits = 0;
    for (int d = 0; d < g_db_count; d++) { if (g_db[d].solved) solved++; total_hits += g_db[d].salt_hits; }
    fprintf(stderr, "\n扫描 %ldMB, 试候选 %ld 个\n", total_scanned/1024/1024, candidates_tried);
    fprintf(stderr, "salt 命中总数：%ld（=0 说明内存里找不到 salt，需换策略）\n", total_hits);
    fprintf(stderr, "解出密钥：%d/%d 个库\n\n", solved, g_db_count);
    fprintf(stderr, "%-28s %-8s %s\n", "库", "salt命中", "解出?");
    for (int d = 0; d < g_db_count; d++) {
        fprintf(stderr, "%-28s %-8ld %s\n", g_db[d].rel, g_db[d].salt_hits,
                g_db[d].solved ? "✓" : (g_db[d].salt_hits > 0 ? "✗(salt在但key没逮到)" : "—(salt不在内存)"));
    }

    /* 写 all_keys.json（兼容 decrypt_db.py） */
    FILE *fp = fopen("all_keys.json", "w");
    if (fp) {
        fprintf(fp, "{\n");
        int first = 1;
        for (int d = 0; d < g_db_count; d++) {
            if (!g_db[d].solved) continue;
            fprintf(fp, "%s  \"%s\": {\"enc_key\": \"%s\"}",
                    first ? "" : ",\n", g_db[d].rel, g_db[d].enc_key_hex);
            first = 0;
        }
        fprintf(fp, "\n}\n");
        fclose(fp);
        fprintf(stderr, "已写 all_keys.json\n");
    }
    return solved > 0 ? 0 : 2;
}
