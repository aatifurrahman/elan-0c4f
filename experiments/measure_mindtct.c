#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <glib.h>
#include "lfs.h"

static int process_image(const char *path, int *out_with_perim, int *out_without_perim) {
    FILE *f = fopen(path, "rb");
    if (!f) {
        return -1;
    }

    char magic[16];
    int w = 0, h = 0, maxval = 0;
    if (fscanf(f, "%15s %d %d %d", magic, &w, &h, &maxval) != 4) {
        fclose(f);
        return -2;
    }
    fgetc(f); // trailing whitespace

    unsigned char *img = g_malloc(w * h);
    if (fread(img, 1, w * h, f) != (size_t)(w * h)) {
        g_free(img);
        fclose(f);
        return -3;
    }
    fclose(f);

    double ppmm = 20.0; // 508 DPI

    for (int mode = 0; mode < 2; mode++) {
        MINUTIAE *minutiae = NULL;
        int *quality_map = NULL, *direction_map = NULL, *low_contrast_map = NULL;
        int *low_flow_map = NULL, *high_curve_map = NULL;
        int map_w = 0, map_h = 0;
        unsigned char *bdata = NULL;
        int bw = 0, bh = 0, bd = 0;

        LFSPARMS *lfsparms = g_memdup2(&g_lfsparms_V2, sizeof(LFSPARMS));
        lfsparms->remove_perimeter_pts = (mode == 0) ? TRUE : FALSE;

        int r = get_minutiae(&minutiae, &quality_map, &direction_map,
                             &low_contrast_map, &low_flow_map, &high_curve_map,
                             &map_w, &map_h, &bdata, &bw, &bh, &bd,
                             img, w, h, 8, ppmm, lfsparms);

        int count = (r == 0 && minutiae) ? minutiae->num : 0;
        if (mode == 0) {
            *out_with_perim = count;
        } else {
            *out_without_perim = count;
        }

        if (minutiae) free_minutiae(minutiae);
        if (quality_map) free(quality_map);
        if (direction_map) free(direction_map);
        if (low_contrast_map) free(low_contrast_map);
        if (low_flow_map) free(low_flow_map);
        if (high_curve_map) free(high_curve_map);
        if (bdata) free(bdata);
        g_free(lfsparms);
    }

    g_free(img);
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        printf("Usage: %s <pgm_file1> [pgm_file2 ...]\n", argv[0]);
        return 1;
    }

    printf("file,with_perimeter_removal,without_perimeter_removal\n");
    for (int i = 1; i < argc; i++) {
        int with_perim = 0, without_perim = 0;
        int rc = process_image(argv[i], &with_perim, &without_perim);
        if (rc == 0) {
            printf("%s,%d,%d\n", argv[i], with_perim, without_perim);
        } else {
            fprintf(stderr, "Error processing %s: rc=%d\n", argv[i], rc);
        }
    }

    return 0;
}
