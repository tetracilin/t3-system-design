# T3 Desk: hướng dẫn nhanh

1. **Mở ứng dụng.** Chạy `T3Desk` (hoặc `python -m t3desk`). Nếu cửa sổ không mở, dùng
   `python -m t3desk --browser` để mở bằng trình duyệt.
2. **Khởi tạo (lần đầu).** Nhập địa chỉ Teable trên NAS, token của riêng bạn, tên và vai trò.
   Bấm kiểm tra kết nối. Người quản trị dùng token có quyền tạo bảng để tạo dự án mới.
3. **Nhập dữ liệu.** Chọn màn hình ở danh sách bên trái, mở biểu mẫu và bấm lưu. Dữ liệu lưu
   thành **bản nháp** trên máy bạn, chưa vào Teable. Hàng nháp luôn được đánh dấu.
4. **Cây quyết định** ở bên phải cho biết bạn đang ở đâu và việc tiếp theo là gì.
5. **Commit.** Bấm Commit để gửi bản nháp lên Teable. Mã (ID) ai gửi trước thì giữ mã đó. Nếu
   mã trùng, ứng dụng đề xuất mã mới cho bạn; bản ghi đã có trong Teable không bị thay đổi.
6. **Sửa bản ghi bị người khác đổi.** Ứng dụng hiện hai phiên bản từng trường để bạn chọn.
7. **Mất kết nối NAS.** Vẫn xem dữ liệu đã lưu và tiếp tục nhập nháp; Commit bị khóa đến khi
   Teable trả lời.
8. **Không xóa dữ liệu.** Bản ghi không dùng nữa được chuyển trạng thái, không bị xóa.
9. **Cổng chốt cấp 1 và cấp 2, chọn kiến trúc** chỉ vai trò System designer được thực hiện.
10. **Gửi RFQ, RFP (plugin).** Ứng dụng hiện đúng nội dung và máy đích để bạn xem trước khi gửi.
    Nội dung không chứa giá của nhà cung cấp khác, ngân sách hay điểm.

Cần trợ giúp: hỏi người phụ trách hệ thống. Chi tiết kỹ thuật xem `README.md`.
