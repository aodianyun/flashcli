// PI0.5 native FP8 calibration runner (SM120) using real observation dirs.
// Usage: pi05_calib <config_json> <artifact_out> <obs_dir> [W] [H]
// obs_dir contains obs_XXXX/{image.rgb,image2.rgb,state.txt,prompt.txt}.
#include "flashrt/cpp/models/pi05/c_api.h"

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <dirent.h>
#include <fstream>
#include <sstream>
#include <string>
#include <sys/stat.h>
#include <vector>

static std::string read_file(const char* path, bool* ok = nullptr) {
    std::ifstream f(path, std::ios::binary);
    if (!f) {
        if (ok) *ok = false;
        return {};
    }
    std::stringstream ss;
    ss << f.rdbuf();
    if (ok) *ok = true;
    return ss.str();
}

static std::vector<int> list_obs(const std::string& root) {
    std::vector<int> ids;
    DIR* d = opendir(root.c_str());
    if (!d) return ids;
    struct dirent* e;
    while ((e = readdir(d)) != nullptr) {
        int id;
        if (std::sscanf(e->d_name, "obs_%d", &id) == 1) ids.push_back(id);
    }
    closedir(d);
    std::sort(ids.begin(), ids.end());
    return ids;
}

static std::vector<float> parse_csv_floats(const std::string& s) {
    std::vector<float> out;
    std::stringstream ss(s);
    std::string tok;
    while (std::getline(ss, tok, ',')) {
        if (!tok.empty()) out.push_back(std::strtof(tok.c_str(), nullptr));
    }
    return out;
}

int main(int argc, char** argv) {
    if (argc < 4) {
        std::fprintf(stderr,
                     "usage: %s <config_json> <artifact_out> <obs_dir> [W] [H]\n",
                     argv[0]);
        return 2;
    }
    const std::string config_json = read_file(argv[1]);
    const char* artifact = argv[2];
    const std::string obs_root = argv[3];
    const int W = argc > 4 ? std::atoi(argv[4]) : 256;
    const int H = argc > 5 ? std::atoi(argv[5]) : 256;

    frt_pi05_calibration_session* session = nullptr;
    int rc = frt_pi05_calibration_create_v1(config_json.c_str(), 99.9, &session);
    if (rc != 0 || session == nullptr) {
        std::fprintf(stderr, "calibration create failed rc=%d: %s\n", rc,
                     frt_pi05_calibration_create_last_error_v1());
        return 1;
    }

    const std::vector<int> ids = list_obs(obs_root);
    if (ids.empty()) {
        std::fprintf(stderr, "no obs_* dirs under %s\n", obs_root.c_str());
        frt_pi05_calibration_destroy_v1(session);
        return 2;
    }
    const char* names[2] = {"image", "wrist_image"};
    const int state_dim = 8;

    int submitted = 0;
    for (int id : ids) {
        char dir[512];
        std::snprintf(dir, sizeof(dir), "%s/obs_%04d", obs_root.c_str(), id);
        bool ok1 = false, ok2 = false;
        std::string f0 = read_file((std::string(dir) + "/image.rgb").c_str(), &ok1);
        std::string f1 = read_file((std::string(dir) + "/image2.rgb").c_str(), &ok2);
        std::string st = read_file((std::string(dir) + "/state.txt").c_str());
        std::string pr = read_file((std::string(dir) + "/prompt.txt").c_str());
        if (!ok1 || !ok2 || f0.size() != size_t(W) * H * 3 ||
            f1.size() != size_t(W) * H * 3) {
            std::fprintf(stderr, "skip %s (bad frames)\n", dir);
            continue;
        }
        while (!pr.empty() && (pr.back() == '\n' || pr.back() == '\r')) pr.pop_back();
        std::vector<float> state = parse_csv_floats(st);
        if ((int)state.size() != state_dim) {
            std::fprintf(stderr, "skip %s (state %zu)\n", dir, state.size());
            continue;
        }
        const void* data[2] = {f0.data(), f1.data()};
        frt_pi05_vision_frame frames[2] = {};
        for (int v = 0; v < 2; ++v) {
            frames[v].struct_size = sizeof(frt_pi05_vision_frame);
            frames[v].name = names[v];
            frames[v].data = data[v];
            frames[v].bytes = size_t(W) * H * 3;
            frames[v].width = W;
            frames[v].height = H;
            frames[v].stride_bytes = W * 3;
            frames[v].pixel_format = FRT_PI05_PIXEL_RGB8;
            frames[v].timestamp_ns = 0;
        }
        frt_pi05_calibration_sample_v1 sample = {};
        sample.struct_size = sizeof(sample);
        sample.prompt = pr.c_str();
        sample.state = state.data();
        sample.n_state = state.size();
        sample.frames = frames;
        sample.n_frames = 2;
        sample.noise = nullptr;
        sample.n_noise = 0;
        sample.noise_seed = 0;
        rc = frt_pi05_calibration_observe_v1(session, &sample);
        if (rc != 0) {
            std::fprintf(stderr, "observe %s failed rc=%d: %s\n", dir, rc,
                         frt_pi05_calibration_last_error_v1(session));
            frt_pi05_calibration_destroy_v1(session);
            return 1;
        }
        submitted++;
    }

    std::printf("observed %llu real samples (submitted %d); finalizing -> %s\n",
                (unsigned long long)frt_pi05_calibration_sample_count_v1(session),
                submitted, artifact);
    rc = frt_pi05_calibration_finalize_v1(session, artifact);
    if (rc != 0) {
        std::fprintf(stderr, "finalize failed rc=%d: %s\n", rc,
                     frt_pi05_calibration_last_error_v1(session));
        frt_pi05_calibration_destroy_v1(session);
        return 1;
    }
    frt_pi05_calibration_destroy_v1(session);
    std::printf("OK artifact written\n");
    return 0;
}
