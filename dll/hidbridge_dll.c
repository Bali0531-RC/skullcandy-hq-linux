#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <stdio.h>

typedef unsigned char BOOLEANx;
typedef struct _HIDD_ATTRIBUTES {
    ULONG Size; USHORT VendorID; USHORT ProductID; USHORT VersionNumber;
} HIDD_ATTRIBUTES, *PHIDD_ATTRIBUTES;

#define SKDY_VID 0x34F0
#define BRIDGE_PORT 38099

static HMODULE g_real = NULL;
static FILE *g_log = NULL;
static SOCKET g_sock = INVALID_SOCKET;
static CRITICAL_SECTION g_cs;
static int g_cs_init = 0;
static int g_wsa = 0;

static void ensure(void) {
    if (!g_real) g_real = LoadLibraryA("hidwine.dll");
    if (!g_cs_init) { InitializeCriticalSection(&g_cs); g_cs_init = 1; }
    if (!g_log) {
        g_log = fopen("Z:\\tmp\\hidbridge-dll.log", "a");
        if (g_log) { fprintf(g_log, "=== bridge dll loaded real=%p ===\n", (void*)g_real); fflush(g_log); }
    }
}
#define LOG(...) do{ ensure(); if(g_log){ fprintf(g_log, __VA_ARGS__); fflush(g_log);} }while(0)
static void* gp(const char* n){ ensure(); return (void*)GetProcAddress(g_real, n); }

/* ---- real attribute check ---- */
static int is_skdy(HANDLE h) {
    typedef BOOLEANx(__stdcall *fn)(HANDLE, PHIDD_ATTRIBUTES);
    static fn f = NULL;
    if (!f) f = (fn)gp("HidD_GetAttributes");
    if (!f) return 0;
    HIDD_ATTRIBUTES a; a.Size = sizeof(a); a.VendorID = 0;
    if (!f(h, &a)) return 0;
    return a.VendorID == SKDY_VID;
}

/* ---- bridge socket ---- */
static int bridge_connect(void) {
    if (!g_wsa) { WSADATA w; WSAStartup(MAKEWORD(2,2), &w); g_wsa = 1; }
    if (g_sock != INVALID_SOCKET) return 1;
    SOCKET s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s == INVALID_SOCKET) return 0;
    struct sockaddr_in addr; memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(BRIDGE_PORT);
    addr.sin_addr.s_addr = htonl(0x7F000001); /* 127.0.0.1 */
    if (connect(s, (struct sockaddr*)&addr, sizeof(addr)) != 0) { closesocket(s); return 0; }
    int one = 1; setsockopt(s, IPPROTO_TCP, TCP_NODELAY, (char*)&one, sizeof(one));
    g_sock = s;
    LOG("bridge connected\n");
    return 1;
}
static void bridge_reset(void) {
    if (g_sock != INVALID_SOCKET) { closesocket(g_sock); g_sock = INVALID_SOCKET; }
}
static int send_all(const char* b, int n) {
    int off = 0;
    while (off < n) { int r = send(g_sock, b + off, n - off, 0); if (r <= 0) return 0; off += r; }
    return 1;
}
static int recv_all(char* b, int n) {
    int off = 0;
    while (off < n) { int r = recv(g_sock, b + off, n - off, 0); if (r <= 0) return 0; off += r; }
    return 1;
}

/* op=1 WRITE output report */
static int bridge_write(const unsigned char* data, ULONG len) {
    EnterCriticalSection(&g_cs);
    int ok = 0;
    for (int attempt = 0; attempt < 2 && !ok; attempt++) {
        if (!bridge_connect()) break;
        unsigned char hdr[4] = { 1, data[0], (unsigned char)(len & 0xFF), (unsigned char)((len >> 8) & 0xFF) };
        if (!send_all((char*)hdr, 4) || !send_all((char*)data, (int)len)) { bridge_reset(); continue; }
        char resp[3];
        if (!recv_all(resp, 3)) { bridge_reset(); continue; }
        ok = resp[0];
    }
    LeaveCriticalSection(&g_cs);
    return ok;
}
/* op=2 GETFEATURE -> fill buf (buf[0] = report id requested) */
static int bridge_getfeature(unsigned char* buf, ULONG len) {
    EnterCriticalSection(&g_cs);
    int got = 0;
    for (int attempt = 0; attempt < 2 && !got; attempt++) {
        if (!bridge_connect()) break;
        unsigned char rid = buf[0];
        unsigned char hdr[4] = { 2, rid, (unsigned char)(len & 0xFF), (unsigned char)((len >> 8) & 0xFF) };
        if (!send_all((char*)hdr, 4)) { bridge_reset(); continue; }
        char rh[3];
        if (!recv_all(rh, 3)) { bridge_reset(); continue; }
        int rl = (unsigned char)rh[1] | ((unsigned char)rh[2] << 8);
        if (rl > (int)len) rl = (int)len;
        if (rl > 0) {
            if (!recv_all((char*)buf, rl)) { bridge_reset(); continue; }
        }
        got = (rh[0] && rl > 0) ? rl : 0;
        if (!rh[0]) got = 0;
        if (got == 0 && rl == 0) { got = 0; break; } /* status ok but empty */
    }
    LeaveCriticalSection(&g_cs);
    return got;
}
/* op=3 SETFEATURE */
static int bridge_setfeature(const unsigned char* data, ULONG len) {
    EnterCriticalSection(&g_cs);
    int ok = 0;
    for (int attempt = 0; attempt < 2 && !ok; attempt++) {
        if (!bridge_connect()) break;
        unsigned char hdr[4] = { 3, data[0], (unsigned char)(len & 0xFF), (unsigned char)((len >> 8) & 0xFF) };
        if (!send_all((char*)hdr, 4) || !send_all((char*)data, (int)len)) { bridge_reset(); continue; }
        char resp[3];
        if (!recv_all(resp, 3)) { bridge_reset(); continue; }
        ok = resp[0];
    }
    LeaveCriticalSection(&g_cs);
    return ok;
}

/* ===== exported wrappers ===== */
__declspec(dllexport) BOOLEANx HidD_GetAttributes(HANDLE h, PHIDD_ATTRIBUTES a) {
    typedef BOOLEANx(__stdcall *fn)(HANDLE, PHIDD_ATTRIBUTES);
    static fn f = NULL; if (!f) f = (fn)gp("HidD_GetAttributes");
    return f ? f(h, a) : 0;
}

__declspec(dllexport) BOOLEANx HidD_SetOutputReport(HANDLE h, PVOID buf, ULONG len) {
    if (is_skdy(h)) {
        int ok = bridge_write((unsigned char*)buf, len);
        LOG("SetOutputReport SKDY len=%lu rid=%02x ok=%d\n", len, ((unsigned char*)buf)[0], ok);
        return ok ? 1 : 0;
    }
    typedef BOOLEANx(__stdcall *fn)(HANDLE, PVOID, ULONG);
    static fn f = NULL; if (!f) f = (fn)gp("HidD_SetOutputReport");
    return f ? f(h, buf, len) : 0;
}

__declspec(dllexport) BOOLEANx HidD_GetInputReport(HANDLE h, PVOID buf, ULONG len) {
    if (is_skdy(h)) {
        int n = bridge_getfeature((unsigned char*)buf, len);
        LOG("GetInputReport SKDY len=%lu rid=%02x -> %d\n", len, ((unsigned char*)buf)[0], n);
        return n > 0 ? 1 : 0;
    }
    typedef BOOLEANx(__stdcall *fn)(HANDLE, PVOID, ULONG);
    static fn f = NULL; if (!f) f = (fn)gp("HidD_GetInputReport");
    return f ? f(h, buf, len) : 0;
}

__declspec(dllexport) BOOLEANx HidD_GetFeature(HANDLE h, PVOID buf, ULONG len) {
    if (is_skdy(h)) {
        int n = bridge_getfeature((unsigned char*)buf, len);
        LOG("GetFeature SKDY len=%lu rid=%02x -> %d\n", len, ((unsigned char*)buf)[0], n);
        return n > 0 ? 1 : 0;
    }
    typedef BOOLEANx(__stdcall *fn)(HANDLE, PVOID, ULONG);
    static fn f = NULL; if (!f) f = (fn)gp("HidD_GetFeature");
    return f ? f(h, buf, len) : 0;
}

__declspec(dllexport) BOOLEANx HidD_SetFeature(HANDLE h, PVOID buf, ULONG len) {
    if (is_skdy(h)) {
        int ok = bridge_setfeature((unsigned char*)buf, len);
        LOG("SetFeature SKDY len=%lu rid=%02x ok=%d\n", len, ((unsigned char*)buf)[0], ok);
        return ok ? 1 : 0;
    }
    typedef BOOLEANx(__stdcall *fn)(HANDLE, PVOID, ULONG);
    static fn f = NULL; if (!f) f = (fn)gp("HidD_SetFeature");
    return f ? f(h, buf, len) : 0;
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID p) {
    (void)h; (void)p;
    if (reason == DLL_PROCESS_ATTACH) ensure();
    return TRUE;
}
