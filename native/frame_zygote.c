/* SPDX-License-Identifier: MIT
 * Lepton fake-identity compatibility for Chromium's app zygote.
 * No kernel credentials or container permissions are changed.
 * Bionic remains authoritative until a Chromium zygote child transitions
 * from its app identity to an Android isolated-service identity.
 */
typedef unsigned int id_t;
typedef unsigned long size_t;
extern void *dlsym(void *, const char *);
extern const char *getprogname(void);
extern int strcmp(const char *, const char *);
extern int snprintf(char *, size_t, const char *, ...);
extern int setenv(const char *, const char *, int);
extern int *__errno(void);

static id_t isolated_uid = (id_t)-1, isolated_gid = (id_t)-1;
static id_t (*original_uid)(void), (*original_gid)(void);
static int (*original_setuid)(id_t), (*original_setgid)(id_t);
static int (*original_getresuid)(id_t *, id_t *, id_t *);
static int (*original_getresgid)(id_t *, id_t *, id_t *);

__attribute__((constructor)) static void resolve(void) {
    void *next = (void *)-1;
    original_uid = dlsym(next, "getuid");
    original_gid = dlsym(next, "getgid");
    original_setuid = dlsym(next, "setuid");
    original_setgid = dlsym(next, "setgid");
    original_getresuid = dlsym(next, "getresuid");
    original_getresgid = dlsym(next, "getresgid");
}

static int zygote_transition(id_t old, id_t next) {
    const char *name = getprogname();
    return old >= 10000 && old < 20000 && next >= 90000 && next <= 99999 &&
        name && (!strcmp(name, "org.chromium.chrome_zygote") ||
                 !strcmp(name, "com.android.chrome_zygote"));
}

static int remember(const char *key, id_t value) {
    char buffer[16];
    snprintf(buffer, sizeof(buffer), "%u", value);
    return setenv(key, buffer, 1);
}

id_t getuid(void) { if (!original_uid) resolve(); return isolated_uid != (id_t)-1 ? isolated_uid : original_uid(); }
id_t geteuid(void) { return getuid(); }
id_t getgid(void) { if (!original_gid) resolve(); return isolated_gid != (id_t)-1 ? isolated_gid : original_gid(); }
id_t getegid(void) { return getgid(); }

int setgid(id_t gid) {
    if (!original_gid) resolve();
    if (isolated_gid != (id_t)-1) {
        if (gid == isolated_gid) return 0;
        *__errno() = 1; return -1;
    }
    if (zygote_transition(original_gid(), gid)) {
        if (remember("PARENT_GID", gid)) return -1;
        isolated_gid = gid; return 0;
    }
    return original_setgid(gid);
}

int setuid(id_t uid) {
    if (!original_uid) resolve();
    if (isolated_uid != (id_t)-1) {
        if (uid == isolated_uid) return 0;
        *__errno() = 1; return -1;
    }
    if (isolated_gid == uid && zygote_transition(original_uid(), uid)) {
        if (remember("PARENT_UID", uid)) return -1;
        isolated_uid = uid; return 0;
    }
    return original_setuid(uid);
}

int setresuid(id_t r, id_t e, id_t s) { (void)r; (void)s; return setuid(e); }
int setresgid(id_t r, id_t e, id_t s) { (void)r; (void)s; return setgid(e); }
int setreuid(id_t r, id_t e) { (void)r; return setuid(e); }
int setregid(id_t r, id_t e) { (void)r; return setgid(e); }

int getresuid(id_t *r, id_t *e, id_t *s) {
    if (!original_getresuid) resolve();
    if (isolated_uid == (id_t)-1) return original_getresuid(r, e, s);
    *r = *e = *s = isolated_uid; return 0;
}
int getresgid(id_t *r, id_t *e, id_t *s) {
    if (!original_getresgid) resolve();
    if (isolated_gid == (id_t)-1) return original_getresgid(r, e, s);
    *r = *e = *s = isolated_gid; return 0;
}
