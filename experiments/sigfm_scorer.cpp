#include <iostream>
#include <vector>
#include <cmath>
#include <opencv2/opencv.hpp>

struct FeatureData {
    std::vector<cv::KeyPoint> keypoints;
    cv::Mat descriptors;
};

FeatureData extract_features(const cv::Mat& raw_img) {
    cv::Mat f;
    raw_img.convertTo(f, CV_32F);

    // 1. Row-banding removal (subtract row median)
    for (int y = 0; y < f.rows; ++y) {
        std::vector<float> row_vals(f.cols);
        for (int x = 0; x < f.cols; ++x) {
            row_vals[x] = f.at<float>(y, x);
        }
        std::nth_element(row_vals.begin(), row_vals.begin() + row_vals.size() / 2, row_vals.end());
        float median_val = row_vals[row_vals.size() / 2];
        for (int x = 0; x < f.cols; ++x) {
            f.at<float>(y, x) -= median_val;
        }
    }

    // 2. Bandpass filter: highpass (sigma=5.0) + lowpass (sigma=0.8)
    cv::Mat blur50, blur08;
    cv::GaussianBlur(f, blur50, cv::Size(0, 0), 5.0);
    f -= blur50;
    cv::GaussianBlur(f, blur08, cv::Size(0, 0), 0.8);
    f = blur08;

    // 3. Normalize to [0, 255]
    cv::Mat norm;
    cv::normalize(f, norm, 0, 255, cv::NORM_MINMAX, CV_8U);

    // 4. Upscale small sensor frames (e.g. 80x80 -> 160x160)
    cv::Mat proc;
    if (norm.cols < 120 || norm.rows < 120) {
        cv::resize(norm, proc, cv::Size(norm.cols * 2, norm.rows * 2), 0, 0, cv::INTER_CUBIC);
    } else {
        proc = norm;
    }

    FeatureData fd;
    auto sift = cv::SIFT::create(0, 3, 0.01, 20.0);
    sift->detectAndCompute(proc, cv::noArray(), fd.keypoints, fd.descriptors);
    return fd;
}

int score_pair(const FeatureData& a, const FeatureData& b) {
    if (a.descriptors.empty() || b.descriptors.empty() || a.keypoints.size() < 3 || b.keypoints.size() < 3) {
        return 0;
    }

    std::vector<std::vector<cv::DMatch>> matches;
    auto bfm = cv::BFMatcher::create();
    bfm->knnMatch(a.descriptors, b.descriptors, matches, 2);

    std::vector<cv::Point2f> pts_a;
    std::vector<cv::Point2f> pts_b;

    for (const auto& m : matches) {
        if (m.size() == 2 && m[0].distance < 0.8 * m[1].distance) {
            pts_a.push_back(a.keypoints[m[0].queryIdx].pt);
            pts_b.push_back(b.keypoints[m[0].trainIdx].pt);
        }
    }

    if (pts_a.size() < 3) {
        return 0;
    }

    cv::Mat inliers;
    cv::Mat affine = cv::estimateAffinePartial2D(pts_a, pts_b, inliers, cv::RANSAC, 4.0);
    if (affine.empty() || inliers.empty()) {
        return 0;
    }

    double a_param = affine.at<double>(0, 0);
    double b_param = affine.at<double>(1, 0);
    double scale = std::sqrt(a_param * a_param + b_param * b_param);
    if (scale < 0.80 || scale > 1.25) {
        return 0;
    }

    int inlier_count = cv::countNonZero(inliers);
    if (inlier_count < 3) {
        return 0;
    }

    float min_x = 1e9f, max_x = -1e9f;
    float min_y = 1e9f, max_y = -1e9f;
    for (int i = 0; i < inliers.rows; ++i) {
        if (inliers.at<uchar>(i, 0)) {
            const auto& pt = pts_a[i];
            if (pt.x < min_x) min_x = pt.x;
            if (pt.x > max_x) max_x = pt.x;
            if (pt.y < min_y) min_y = pt.y;
            if (pt.y > max_y) max_y = pt.y;
        }
    }

    if ((max_x - min_x) < 25.0f || (max_y - min_y) < 25.0f) {
        return 0;
    }

    return inlier_count;
}

int main(int argc, char** argv) {
    if (argc < 3) {
        std::cerr << "Usage: " << argv[0] << " <image_a> <image_b>\n";
        return 1;
    }

    cv::Mat img_a = cv::imread(argv[1], cv::IMREAD_GRAYSCALE);
    cv::Mat img_b = cv::imread(argv[2], cv::IMREAD_GRAYSCALE);

    if (img_a.empty() || img_b.empty()) {
        std::cerr << "Error loading images\n";
        return 1;
    }

    FeatureData fd_a = extract_features(img_a);
    FeatureData fd_b = extract_features(img_b);

    int score = score_pair(fd_a, fd_b);
    std::cout << score << "\n";
    return 0;
}
