"""Exercise XRDP's actual allocator and disconnect block with an in-memory transport.

Pass a trusted chansrv.c from XRDP 0.10.6.1 or the pinned development tree. This is a source-level regression,
not a live RDP acceptance test. No server is started or modified.
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path


def block(source: str, marker: str) -> str:
    start = source.index(marker)
    opening = source.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[opening:end]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--expect-fixed", action="store_true")
    args = parser.parse_args()
    source = args.source.read_text()
    dechunkers = "struct dyn_dechunker *dc;" in source
    declaration = "static struct chansrv_drdynvc g_drdynvcs["
    definitions = source[
        source.index("#define CHANSRV_DRDYNVC_STATUS_CLOSED") : source.index(
            declaration
        )
    ]
    allocation = block(source, "chansrv_drdynvc_open(const char *name")
    disconnect = block(source, "if (trans_check_wait_objs(g_con_trans) != 0)")
    header = r"""
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#define DRDYNVC_CHANNEL_COUNT 256
static int allocated_dechunkers, freed_dechunkers;
struct trans { void *callback_data; } transport;
struct xrdp_api_data { int chan_flags; };
struct list { int count; struct trans *items[512]; } clients;
static struct list *g_api_con_trans_list=&clients;
static int deleted;
#define g_free free
#define g_memset memset
static struct trans *list_get_item(struct list *l,int index) { return l->items[index]; }
static void list_remove_item(struct list *l,int index) {
 memmove(l->items+index,l->items+index+1,(l->count-index-1)*sizeof(l->items[0])); l->count--;
}
static void dispose(struct trans *t) { if(t != &transport) {free(t);deleted++;} }
static void client(int flags) {
 struct trans *t=calloc(1,sizeof(*t)); struct xrdp_api_data *ad=calloc(1,sizeof(*ad));
 if(!t || !ad) exit(10);
 ad->chan_flags=flags; t->callback_data=ad; clients.items[clients.count++]=t;
}
struct stream { int placeholder; } stream;
static struct trans *g_con_trans;
static struct { int is_connected; } g_session_state;
struct chansrv_drdynvc_procs {
 int (*open_response)(int,int); int (*close_response)(int);
 int (*data_first)(int,char*,int,int); int (*data)(int,char*,int);
};
#define LOG_DEVEL(...) ((void)0)
#define out_uint32_le(s,n) ((void)(s),(void)(n))
#define out_uint8a(s,n,c) ((void)(s),(void)(n),(void)(c))
#define s_mark_end(s) ((void)(s))
#define g_strlen strlen
#define clipboard_deinit() ((void)0)
#define sound_deinit() ((void)0)
#define devredir_deinit() ((void)0)
#define rail_deinit() ((void)0)
#define trans_delete(t) dispose(t)
#define xrdpapi_send_session_state_event_all() 0
#define setup_listen() 0
static struct stream *trans_get_out_s(struct trans *t,int size) {
 (void)size; return t ? &stream : NULL;
}
static int trans_write_copy(struct trans *t) { return t ? 0 : 1; }
"""
    if dechunkers:
        header = header.replace(
            "int (*data_first)(int,char*,int,int); int (*data)(int,char*,int);",
            "int (*data_first)(int,struct stream*,int); int (*data)(int,struct stream*);",
        )
        header += r"""
struct dyn_dechunker { int live; };
static struct dyn_dechunker *dyn_dechunker_init(const char *name) {
 (void)name;
 struct dyn_dechunker *dc=calloc(1,sizeof(*dc));
 if(!dc) exit(11);
 dc->live=1; allocated_dechunkers++; return dc;
}
static void dyn_dechunker_free(struct dyn_dechunker *dc) {
 if(dc) { if(dc->live!=1) exit(12); dc->live=0; freed_dechunkers++; free(dc); }
}
"""
    program = header + definitions + "\nstatic struct chansrv_drdynvc g_drdynvcs[256];\n"
    program += "\n#define EXPECT_DECHUNKERS " + str(int(dechunkers)) + "\n"
    program += (
        "int chansrv_drdynvc_open(const char *name,int flags,struct chansrv_drdynvc_procs *procs,int *chan_id)\n"
        + allocation
    )
    fixed = "drdynvc_reset_all();" in disconnect
    if args.expect_fixed and not fixed:
        raise RuntimeError("Expected disconnect channel reset is absent")
    if fixed:
        program += "\nstatic void drdynvc_reset_all(void)\n" + block(
            source, "drdynvc_reset_all(void)"
        )
    program += (
        "\nstatic void disconnect_peer(void) { int error; do " + disconnect + " while (0); }\n"
    )
    program += "\n#define EXPECT_FIXED " + str(int(fixed)) + "\n"
    program += r"""
int main(void) {
 struct chansrv_drdynvc_procs procs = {0};
 client(0);
 for (int cycle=1;cycle<=1000;cycle++) {
  g_con_trans=&transport; g_session_state.is_connected=1;
  for (int channel=0;channel<2;channel++) {
   int id=0;
   if (chansrv_drdynvc_open(channel ? "TEST-CHANNEL-B" : "TEST-CHANNEL-A",3,&procs,&id)) {
    int used=0;
    for(int i=1;i<256;i++) used += g_drdynvcs[i].status != CHANSRV_DRDYNVC_STATUS_CLOSED;
    printf("{\"failed_cycle\":%d,\"occupied_slots\":%d,\"unassigned_id\":%d}\n",cycle,used,id);
    return !EXPECT_FIXED && cycle==128 && used==255 && id==0 ? 0 : 2;
   }
   client(3);
  }
  disconnect_peer();
  if(EXPECT_FIXED && (clients.count!=1 || deleted!=cycle*2)) return 4;
  if(EXPECT_FIXED && EXPECT_DECHUNKERS &&
     (allocated_dechunkers!=cycle*2 || freed_dechunkers!=allocated_dechunkers)) return 5;
  if(EXPECT_FIXED) {
   for(int i=0;i<256;i++)
    if(g_drdynvcs[i].status!=CHANSRV_DRDYNVC_STATUS_CLOSED) return 6;
  }
 }
 printf("{\"completed_cycles\":1000,\"static_clients_preserved\":%d,\"dynamic_clients_closed\":%d}\n",clients.count,deleted);
 printf("{\"allocated_dechunkers\":%d,\"freed_dechunkers\":%d}\n",allocated_dechunkers,freed_dechunkers);
 return EXPECT_FIXED ? 0 : 3;
}
"""
    with tempfile.TemporaryDirectory(prefix="xrdp-slots-") as temporary:
        path = Path(temporary) / "probe.c"
        path.write_text(program)
        executable = Path(temporary) / "probe"
        subprocess.run(
            ["cc", "-std=c11", "-Wall", "-Wextra", str(path), "-o", str(executable)],
            check=True,
            timeout=30,
        )
        subprocess.run([str(executable)], check=True, timeout=5)


if __name__ == "__main__":
    main()
