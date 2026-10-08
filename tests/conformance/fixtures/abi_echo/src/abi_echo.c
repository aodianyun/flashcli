/* Conformance fixture: minimal native-abi producer.
 *
 * Reference implementation of docs/bundle_execution_abi.md section 7. Exports
 * exactly FRT_MODEL_RUNTIME_OPEN_V1_SYMBOL and returns a retained
 * frt_model_runtime_v1 whose prefix is consistent (abi_version + struct_size).
 * It performs no model work; hosts only need to prove open + prefix probing.
 *
 * Compiles against the real FlashRT header so the fixture cannot drift from
 * the ABI it emulates:
 *   cc -shared -fPIC -o libabi_echo.so abi_echo.c -I<FLASHRT_RUNTIME_INCLUDE>
 */
#include <stdlib.h>
#include <string.h>

#include "flashrt/model_runtime.h"

static frt_model_runtime_v1 g_model;
static int g_inited = 0;
static char g_last_config[1024];

int frt_model_runtime_open_v1(const char *config_json, frt_model_runtime_v1 **out) {
    if (out == NULL) {
        return -1;
    }
    if (!g_inited) {
        memset(&g_model, 0, sizeof(g_model));
        g_model.abi_version = FRT_MODEL_RUNTIME_ABI_VERSION;
        g_model.struct_size = (uint32_t)sizeof(frt_model_runtime_v1);
        g_inited = 1;
    }
    if (config_json != NULL) {
        strncpy(g_last_config, config_json, sizeof(g_last_config) - 1);
        g_last_config[sizeof(g_last_config) - 1] = '\0';
    } else {
        g_last_config[0] = '\0';
    }
    *out = &g_model;
    return 0;
}

/* Test-only accessor: lets the conformance runner assert config_json plumbing. */
const char *abi_echo_last_config(void) {
    return g_last_config;
}
