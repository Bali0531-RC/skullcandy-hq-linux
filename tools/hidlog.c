/*
 * hidlog.c - a logging pass-through hid.dll for capturing a headset's HID
 * protocol under Wine.
 *
 * Install exactly like the bridge DLL, but built from this file: it forwards
 * every HID call to the real Wine hid.dll (shipped renamed as hidwine.dll) and
 * logs the report-I/O calls (with payloads) to Z:\tmp\hid-shim.log. Use it to
 * see what command bytes the Skull-HQ app sends to a *new* model and what the
 * replies look like, so the protocol can be supported.
 *
 * Build (x86_64):
 *   x86_64-w64-mingw32-gcc -O2 -shared -o hidlog.dll hidlog.c ../dll/hid.def -lkernel32
 * Install:
 *   cp /usr/lib/wine/x86_64-windows/hid.dll  <AIROHA_DIR>/hidwine.dll
 *   cp hidlog.dll                            <AIROHA_DIR>/hid.dll
 *   WINEDLLOVERRIDES="hid=n,b" wine Skull-HQ.exe
 *   tail -f /tmp/hid-shim.log
 *
 * (<AIROHA_DIR> is the folder that contains AirohaHidCoreLib.dll.)
 *
 * NOTE: this exports the same 5 wrapped names as ../dll/hid.def and forwards the
 * other 39 to hidwine, so it reuses ../dll/hid.def unchanged.
 */
#include <windows.h>
#include <stdio.h>

typedef unsigned char BOOLEANx;
typedef struct _HIDD_ATTRIBUTES {
    ULONG Size; USHORT VendorID; USHORT ProductID; USHORT VersionNumber;
} HIDD_ATTRIBUTES, *PHIDD_ATTRIBUTES;

static HMODULE g_real = NULL;
static FILE *g_log = NULL;

static void ensure(void) {
    if (!g_real) g_real = LoadLibraryA("hidwine.dll");
    if (!g_log) {
        g_log = fopen("Z:\\tmp\\hid-shim.log", "a");
        if (g_log) { fprintf(g_log, "=== hidlog loaded real=%p ===\n", (void*)g_real); fflush(g_log); }
    }
}
#define LOG(...) do{ ensure(); if(g_log){ fprintf(g_log, __VA_ARGS__); fflush(g_log);} }while(0)
static void* gp(const char* n){ ensure(); return (void*)GetProcAddress(g_real, n); }
static void hx(const char* t, const unsigned char* d, int n){
    if(!g_log) return; fprintf(g_log, "%s[%d]:", t, n);
    int l = n > 48 ? 48 : n;
    for(int i=0;i<l;i++) fprintf(g_log, " %02x", d[i]);
    if(n>48) fprintf(g_log, " ...");
    fprintf(g_log, "\n"); fflush(g_log);
}

__declspec(dllexport) BOOLEANx HidD_GetAttributes(HANDLE h, PHIDD_ATTRIBUTES a){
    typedef BOOLEANx(__stdcall *fn)(HANDLE,PHIDD_ATTRIBUTES); static fn f=NULL; if(!f) f=(fn)gp("HidD_GetAttributes");
    BOOLEANx r=f?f(h,a):0;
    LOG("HidD_GetAttributes(h=%p)=%d vid=%04x pid=%04x\n", h, r, a?a->VendorID:0, a?a->ProductID:0);
    return r;
}
__declspec(dllexport) BOOLEANx HidD_SetOutputReport(HANDLE h, PVOID b, ULONG len){
    typedef BOOLEANx(__stdcall *fn)(HANDLE,PVOID,ULONG); static fn f=NULL; if(!f) f=(fn)gp("HidD_SetOutputReport");
    LOG("HidD_SetOutputReport(h=%p,len=%lu)\n", h, len); hx("  OUT", (unsigned char*)b, (int)len);
    BOOLEANx r=f?f(h,b,len):0; LOG("  = %d (err=%lu)\n", r, GetLastError()); return r;
}
__declspec(dllexport) BOOLEANx HidD_GetInputReport(HANDLE h, PVOID b, ULONG len){
    typedef BOOLEANx(__stdcall *fn)(HANDLE,PVOID,ULONG); static fn f=NULL; if(!f) f=(fn)gp("HidD_GetInputReport");
    BOOLEANx r=f?f(h,b,len):0;
    LOG("HidD_GetInputReport(h=%p,len=%lu)=%d (err=%lu)\n", h, len, r, GetLastError());
    if(r) hx("  IN", (unsigned char*)b, (int)len);
    return r;
}
__declspec(dllexport) BOOLEANx HidD_SetFeature(HANDLE h, PVOID b, ULONG len){
    typedef BOOLEANx(__stdcall *fn)(HANDLE,PVOID,ULONG); static fn f=NULL; if(!f) f=(fn)gp("HidD_SetFeature");
    LOG("HidD_SetFeature(h=%p,len=%lu)\n", h, len); hx("  SF", (unsigned char*)b, (int)len);
    BOOLEANx r=f?f(h,b,len):0; LOG("  = %d (err=%lu)\n", r, GetLastError()); return r;
}
__declspec(dllexport) BOOLEANx HidD_GetFeature(HANDLE h, PVOID b, ULONG len){
    typedef BOOLEANx(__stdcall *fn)(HANDLE,PVOID,ULONG); static fn f=NULL; if(!f) f=(fn)gp("HidD_GetFeature");
    BOOLEANx r=f?f(h,b,len):0;
    LOG("HidD_GetFeature(h=%p,len=%lu)=%d (err=%lu)\n", h, len, r, GetLastError());
    if(r) hx("  GF", (unsigned char*)b, (int)len);
    return r;
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID p){ (void)h;(void)p; if(reason==DLL_PROCESS_ATTACH) ensure(); return TRUE; }
