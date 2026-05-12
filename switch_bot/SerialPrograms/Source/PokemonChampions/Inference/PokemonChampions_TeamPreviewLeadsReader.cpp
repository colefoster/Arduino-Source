/*  Pokemon Champions Team Preview Leads Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 */

#include <vector>
#include <queue>
#include <cstdint>
#include "CommonFramework/ImageTypes/ImageRGB32.h"
#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonTools/OCR/OCR_RawOCR.h"
#include "PokemonChampions_TeamPreviewLeadsReader.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


TeamPreviewLeadsReader::TeamPreviewLeadsReader(){
    //  Boxes drawn by user 2026-05-07 on the number-tag area. Coords mirror
    //  CROP_DEFS["TeamPreviewLockedInReader"] in dashboard/server.py.
    m_slot_boxes[0] = ImageFloatBox(0.1599, 0.1747, 0.0270, 0.0532);
    m_slot_boxes[1] = ImageFloatBox(0.1561, 0.2872, 0.0287, 0.0540);
    m_slot_boxes[2] = ImageFloatBox(0.1586, 0.4048, 0.0299, 0.0615);
    m_slot_boxes[3] = ImageFloatBox(0.1578, 0.5218, 0.0316, 0.0577);
    m_slot_boxes[4] = ImageFloatBox(0.1599, 0.6395, 0.0308, 0.0660);
    m_slot_boxes[5] = ImageFloatBox(0.1586, 0.7526, 0.0274, 0.0637);
}


TeamPreviewLeadsReader::TeamPreviewLeadsReader(
    const std::array<ImageFloatBox, 6>& boxes
){
    m_slot_boxes = boxes;
}


//  Selecting-screen digit-badge boxes drawn by user on
//  team_preview_selecting/screenshot-20260427-132030165558.png.
std::array<ImageFloatBox, 6> TeamPreviewLeadsReader::selecting_screen_boxes(){
    return {
        ImageFloatBox(0.0462, 0.1699, 0.0253, 0.0527),
        ImageFloatBox(0.0462, 0.2865, 0.0240, 0.0554),
        ImageFloatBox(0.0476, 0.4017, 0.0234, 0.0536),
        ImageFloatBox(0.0467, 0.5218, 0.0246, 0.0476),
        ImageFloatBox(0.0466, 0.6375, 0.0223, 0.0484),
        ImageFloatBox(0.0466, 0.7555, 0.0229, 0.0522),
    };
}


//  Yellow-paint + invert + flood-fill-from-edges binarization. Mirror of
//  _yellow_inner_image in dashboard/server.py.
//
//  Steps:
//    1. yellow pixel  -> bin_inv = true (was bg, becomes black after invert)
//    2. dark pixel    -> bin_inv = false (was outline, becomes white)
//    3. light non-yellow -> bin_inv = true (inner of digit, becomes black)
//    4. flood-fill from edges over true pixels -> mark as "outside bg"
//    5. surviving true pixels (NOT marked) = inner trapped center -> emit BLACK
//    6. everything else -> WHITE
//
//  Output: clean black silhouette of the digit's inner counter on white
//  background. Tesseract SINGLE_CHAR handles this.
static ImageRGB32 inner_silhouette(const ImageViewRGB32& crop){
    size_t w = crop.width();
    size_t h = crop.height();
    if (w == 0 || h == 0) return ImageRGB32(1, 1);

    const size_t scale = 3;
    const size_t W = w * scale;
    const size_t H = h * scale;

    //  Per-pixel classification (after upscale).
    std::vector<uint8_t> bin_inv(W * H, 0);  //  1 = "black after invert" candidate
    for (size_t y = 0; y < h; y++){
        for (size_t x = 0; x < w; x++){
            uint32_t pixel = crop.pixel(x, y);
            uint8_t r = (pixel >> 0) & 0xFF;
            uint8_t g = (pixel >> 8) & 0xFF;
            uint8_t b = (pixel >> 16) & 0xFF;

            bool is_yellow = (r > 150) && (g > 150) && (b < 140)
                             && (r > b + 40) && (g > b + 40);
            uint8_t cls;
            if (is_yellow){
                cls = 1;  //  bg yellow -> white -> invert -> black
            }else{
                int brightness = (int(r) + int(g) + int(b)) / 3;
                if (brightness < 130){
                    cls = 0;  //  dark outline -> invert -> white
                }else{
                    cls = 1;  //  light inner -> invert -> black
                }
            }
            for (size_t sy = 0; sy < scale; sy++){
                for (size_t sx = 0; sx < scale; sx++){
                    bin_inv[(y*scale + sy) * W + (x*scale + sx)] = cls;
                }
            }
        }
    }

    //  Flood-fill from edges over `1` pixels.
    std::vector<uint8_t> visited(W * H, 0);
    std::vector<std::pair<size_t, size_t>> stack;
    auto push_seed = [&](size_t x, size_t y){
        size_t idx = y * W + x;
        if (bin_inv[idx] && !visited[idx]){
            visited[idx] = 1;
            stack.emplace_back(x, y);
        }
    };
    for (size_t x = 0; x < W; x++){ push_seed(x, 0); push_seed(x, H - 1); }
    for (size_t y = 0; y < H; y++){ push_seed(0, y); push_seed(W - 1, y); }
    while (!stack.empty()){
        auto [x, y] = stack.back();
        stack.pop_back();
        const ssize_t dx[4] = {1, -1, 0, 0};
        const ssize_t dy[4] = {0, 0, 1, -1};
        for (int k = 0; k < 4; k++){
            ssize_t nx = ssize_t(x) + dx[k];
            ssize_t ny = ssize_t(y) + dy[k];
            if (nx < 0 || ny < 0 || nx >= ssize_t(W) || ny >= ssize_t(H)) continue;
            size_t nidx = size_t(ny) * W + size_t(nx);
            if (bin_inv[nidx] && !visited[nidx]){
                visited[nidx] = 1;
                stack.emplace_back(size_t(nx), size_t(ny));
            }
        }
    }

    //  Compose final image: trapped `1` (not visited) -> black, else white.
    ImageRGB32 out(W, H);
    for (size_t y = 0; y < H; y++){
        for (size_t x = 0; x < W; x++){
            size_t idx = y * W + x;
            uint32_t color = (bin_inv[idx] && !visited[idx])
                                 ? 0xFF000000u   //  black ARGB
                                 : 0xFFFFFFFFu;  //  white ARGB
            out.pixel(x, y) = color;
        }
    }
    return out;
}


//  Tesseract result -> {1,2,3,4} or 0 (bench/unread).
static char normalize_lead_digit(const std::string& raw){
    for (char c : raw){
        if (c >= '1' && c <= '4') return c;
        //  1-shape inner counter is a thin slash; reliably misreads as 7/|//
        if (c == '7' || c == '|' || c == '/') return '1';
    }
    return 0;
}


TeamPreviewLeadsResult TeamPreviewLeadsReader::read(
    Logger& logger, const ImageViewRGB32& screen
) const{
    TeamPreviewLeadsResult out;

    for (uint8_t slot = 0; slot < 6; slot++){
        ImageViewRGB32 cropped = extract_box_reference(screen, m_slot_boxes[slot]);
        ImageRGB32 silhouette = inner_silhouette(cropped);
        std::string raw = OCR::ocr_read(
            Language::English, silhouette, OCR::PageSegMode::SINGLE_CHAR
        );
        out.raw_ocr[slot] = raw;
        char d = normalize_lead_digit(raw);
        out.digit_per_slot[slot] = d;
    }

    //  Build send-out order: slot whose digit == '1' first, then '2' etc.
    for (char want = '1'; want <= '4'; want++){
        for (uint8_t slot = 0; slot < 6; slot++){
            if (out.digit_per_slot[slot] == want){
                out.leads.push_back(slot);
                break;
            }
        }
    }

    (void)logger;
    return out;
}


}}}
