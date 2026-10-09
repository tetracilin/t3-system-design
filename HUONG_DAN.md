# T3 Desk: hướng dẫn nhanh

1. **Mở ứng dụng.** Chạy `T3Desk` (hoặc `python -m t3desk`). Nếu cửa sổ không mở, dùng
   `python -m t3desk --browser` để mở bằng trình duyệt.
2. **Khởi tạo (lần đầu).** Nhập địa chỉ Teable trên NAS, token của riêng bạn, tên và vai trò.
   Bấm kiểm tra kết nối. Người quản trị dùng token có quyền tạo bảng để tạo dự án mới.
3. **Nhập dữ liệu.** Chọn màn hình ở danh sách bên trái (ngăn 1), chọn dòng ở ngăn 2, rồi **gõ thẳng
   vào ô** của bảng ở ngăn 3 (Enter lưu ô và xuống dòng, Tab sang phải, Esc hủy ô, F2 sửa). Gõ vào
   dòng cuối (có dấu ＊) để thêm dòng mới. Mỗi ô lưu thành **bản nháp** trên máy bạn, chưa vào Teable;
   hàng nháp nền vàng, ô lỗi nền đỏ kèm lý do. Ô chọn mã hiện dạng `mã - tên`, gõ để lọc.
4. **Bốn ngăn.** Ngăn 1: menu và cây quyết định (✓ bước đã xong, ▶ bạn đang ở đây, kèm hướng dẫn).
   Ngăn 2: danh sách hoặc sơ đồ hệ thống. Ngăn 3: bảng. Ngăn 4: ngữ cảnh của dòng đang chọn, **ghi chú**
   (viết Markdown, ghi rõ người viết, chỉ người viết sửa hoặc hủy) và trợ lý Hermes (chưa bật).
   Phím tắt: Alt+1..4 nhảy giữa các ngăn, Ctrl+K tìm nhanh, ? xem bảng phím tắt, F1 xem cây quyết định lớn.
   **Thư viện hạng mục:** đừng gõ lại một hệ con hay linh kiện đã có. Ở màn hình Cây hệ thống, tìm trong khung
   Thư viện (mã, tên, hãng, model, SKU) rồi bấm ＋ Thêm, bấm Enter, hoặc kéo vào một nút. Chưa có thì gõ tên mới và
   Enter: ứng dụng tạo hạng mục **chỗ giữ chỗ** và đặt vào hệ thống; giao cho một người điền hãng, model, SKU, chức
   năng rồi đổi tình trạng sang Đã điền. Kiến trúc có cột Hệ con cấp 1: bấm **Tạo khung** để tạo sẵn các hệ con giữ chỗ.
5. **Commit.** Bấm Commit để gửi bản nháp lên Teable. Mã (ID) ai gửi trước thì giữ mã đó. Nếu
   mã trùng, ứng dụng đề xuất mã mới cho bạn; bản ghi đã có trong Teable không bị thay đổi.
6. **Sửa bản ghi bị người khác đổi.** Ứng dụng hiện hai phiên bản từng trường để bạn chọn.
7. **Mất kết nối NAS.** Vẫn xem dữ liệu đã lưu và tiếp tục nhập nháp; Commit bị khóa đến khi
   Teable trả lời.
8. **Không xóa dữ liệu.** Bản ghi không dùng nữa được chuyển trạng thái, không bị xóa.
9. **Cổng chốt cấp 1 và cấp 2, chọn kiến trúc** chỉ vai trò System designer được thực hiện.
10. **Gửi RFQ, RFP (plugin).** Ứng dụng hiện đúng nội dung và máy đích để bạn xem trước khi gửi.
    Nội dung không chứa giá của nhà cung cấp khác, ngân sách hay điểm.

11. **Tỷ giá** (màn hình Khởi tạo, phần cài đặt dự án): nhập số đồng cho 1 đơn vị ngoại tệ, ví dụ
    `1 EUR = 27000 VND`, `1 USD = 25000 VND`; VND luôn bằng 1. Không nhập 0.027: giá trị nhỏ hơn 1
    bị từ chối. Tỷ giá mặc định là số tạm, cần xác nhận tỷ giá thật. Các dòng `ty_gia_*` cũ (đơn vị
    triệu đồng) không còn dùng và không bị xóa. Chi phí vẫn hiện theo triệu đồng.

Cần trợ giúp: hỏi người phụ trách hệ thống. Chi tiết kỹ thuật xem `README.md`.
