#include "sigfm.h"
#include <opencv2/opencv.hpp>
#include <iostream>
#include <fstream>
#include <string>
#include <vector>

static int score_image_pair(const std::string& path_a, const std::string& path_b, SigfmMatchDetails* details = nullptr) {
    cv::Mat img_a = cv::imread(path_a, cv::IMREAD_GRAYSCALE);
    cv::Mat img_b = cv::imread(path_b, cv::IMREAD_GRAYSCALE);

    if (img_a.empty() || img_b.empty()) {
        std::cerr << "Error: failed to load " << (img_a.empty() ? path_a : path_b) << "\n";
        return -1;
    }

    if (!img_a.isContinuous()) img_a = img_a.clone();
    if (!img_b.isContinuous()) img_b = img_b.clone();

    SigfmImgInfo* info_a = sigfm_extract(img_a.data, img_a.cols, img_a.rows);
    SigfmImgInfo* info_b = sigfm_extract(img_b.data, img_b.cols, img_b.rows);

    if (!info_a || !info_b) {
        if (info_a) sigfm_free_info(info_a);
        if (info_b) sigfm_free_info(info_b);
        if (details) {
            std::memset(details, 0, sizeof(*details));
            details->reason = SIGFM_REJECT_TOO_FEW_KEYPOINTS;
        }
        return 0;
    }

    int score = sigfm_match_score_detailed(info_a, info_b, details);
    sigfm_free_info(info_a);
    sigfm_free_info(info_b);
    return score;
}

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <image_a> <image_b>\n"
                  << "   or: " << argv[0] << " --details <image_a> <image_b>\n"
                  << "   or: " << argv[0] << " --batch [pairs_file]\n"
                  << "   or: " << argv[0] << " --batch-details [pairs_file]\n";
        return 1;
    }

    std::string arg1 = argv[1];
    if (arg1 == "--details" && argc >= 4) {
        SigfmMatchDetails d;
        int s = score_image_pair(argv[2], argv[3], &d);
        if (s < 0) return 1;
        std::cout << "Score:       " << d.score << "\n"
                  << "Reason:      " << sigfm_reject_reason_to_str(d.reason) << "\n"
                  << "Fail Mask:   0x" << std::hex << d.fail_mask << std::dec << "\n"
                  << "Kpts Probe:  " << d.kpts_probe << "\n"
                  << "Kpts Enroll: " << d.kpts_enrolled << "\n"
                  << "Candidates:  " << d.candidate_pairs << "\n"
                  << "Scale:       " << d.scale << "\n"
                  << "Inliers:     " << d.inliers << "\n"
                  << "Spread X:    " << d.spread_x << "\n"
                  << "Spread Y:    " << d.spread_y << "\n"
                  << "Duration ms: " << d.duration_ms << "\n";
        return 0;
    }

    if (arg1 == "--batch" || arg1 == "--batch-details") {
        bool detailed = (arg1 == "--batch-details");
        std::istream* input_stream = &std::cin;
        std::ifstream file_stream;
        if (argc >= 3) {
            file_stream.open(argv[2]);
            if (!file_stream.is_open()) {
                std::cerr << "Error opening batch file: " << argv[2] << "\n";
                return 1;
            }
            input_stream = &file_stream;
        }

        std::string p_a, p_b;
        while (*input_stream >> p_a >> p_b) {
            if (detailed) {
                SigfmMatchDetails d;
                int s = score_image_pair(p_a, p_b, &d);
                std::cout << s << " " << sigfm_reject_reason_to_str(d.reason) << " "
                          << d.fail_mask << " "
                          << d.kpts_probe << " " << d.kpts_enrolled << " "
                          << d.candidate_pairs << " " << d.scale << " "
                          << d.inliers << " " << d.spread_x << " " << d.spread_y << " "
                          << d.duration_ms << "\n";
            } else {
                int s = score_image_pair(p_a, p_b);
                std::cout << s << "\n";
            }
        }
        return 0;
    }

    if (argc < 3) {
        std::cerr << "Usage: " << argv[0] << " <image_a> <image_b>\n";
        return 1;
    }

    int score = score_image_pair(argv[1], argv[2]);
    if (score < 0) {
        return 1;
    }
    std::cout << score << "\n";
    return 0;
}
