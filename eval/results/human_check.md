# Human check

Grade each answer against the reference: correct / partial / wrong. The mode
(agent or RAG-only) and the LLM grade are hidden; see human_check_key.json
after grading.

## 1. t10: Lãi suất tái cấp vốn của Ngân hàng Nhà nước hiện nay là bao nhiêu?

**Reference:** Current rate = latest refinancing-rate change: 4.5% since 2023-06-19 (announced 2023-06-16); no change after that in the data. SBV press 2026 (sbv_press_2026_q1_003, sbv_press_2026_q2_002) says policy rates were kept unchanged. SQL: t10

**Answer:**

> **Trả lời ngắn**
> Theo dữ liệu hiện có, mức lãi suất tái cấp vốn được ghi nhận gần nhất là 4,5%, có hiệu lực từ ngày 19/6/2023; dữ liệu chưa xác minh độc lập mức hiện hành trong năm 2026.
>
> **Giải thích thêm**
> - **lãi suất tái cấp vốn**: Đây là mức lãi suất Ngân hàng Nhà nước áp dụng khi cho các tổ chức tín dụng vay vốn.
>
> **Nguồn**
> - Bảng `policy_events`: các lần NHNN đổi lãi suất điều hành (theo thông cáo của NHNN)

**Your grade:** [ ] correct  [ ] partial  [ ] wrong

**Note:**

## 2. t02: Hôm qua MB Bank đóng cửa giá bao nhiêu?

**Reference:** Relative day, kept as written. Reference (decided 2026-11-17): yesterday (2026-11-16) has no data; the latest close is 2026-11-10, MBB 19,400 (adjusted). The answer must say yesterday is not in the data and give the 2026-11-10 close. Run-date dependent: data ends 2026-11-10. SQL: t02

**Answer:**

> **Trả lời ngắn**
> Mình chưa có dữ liệu giá đóng cửa của cổ phiếu MB Bank cho ngày 16/11/2026, nên chưa thể xác nhận mức giá hôm qua.
>
> **Giải thích thêm**
> - **giá đóng cửa**: Đây là mức giá của cổ phiếu tại thời điểm kết thúc phiên giao dịch trong ngày.

**Your grade:** [ ] correct  [ ] partial  [ ] wrong

**Note:**

## 3. t15: Giá thuê căn hộ ở Thủ Đức hiện nay khoảng bao nhiêu?

**Reference:** Real estate rents not in scope: decline and suggest in-scope questions.

**Answer:**

> **Trả lời ngắn**
> Mình chưa có dữ liệu về mức giá thuê căn hộ tại Thủ Đức hiện nay. Báo cáo tháng 9/2026 chỉ ghi giá thuê nhà trên phạm vi cả nước tăng 0,10% so với tháng trước, không nêu giá tiền hay mức riêng của Thủ Đức.
>
> **Giải thích thêm**
> - **giá thuê nhà**: Đây là khoản tiền người thuê trả để sử dụng nhà trong một khoảng thời gian.
> - **so với tháng trước**: Đây là cách so sánh mức của tháng được nêu với mức của tháng liền trước.
>
> **Nguồn**
> - Báo cáo tình hình kinh tế – xã hội quý III và 9 tháng năm 2026 (kỳ 2026-09): https://www.nso.gov.vn/tin-tuc-thong-ke/2026/10/bao-cao-tinh-hinh-kinh-te-xa-hoi-quy-iii-va-9-thang-nam-2026/

**Your grade:** [ ] correct  [ ] partial  [ ] wrong

**Note:**

## 4. t13: Chỉ thị 01 năm 2026 của NHNN đặt mục tiêu tăng trưởng tín dụng bao nhiêu?

**Reference:** Doc sbv_directive_2026_01, chunk sbv_directive_2026_01_002: system credit growth about 15%, adjusted up or down as conditions require.

**Answer:**

> **Trả lời ngắn**
> Chỉ thị 01/CT-NHNN năm 2026 dự kiến tăng trưởng tín dụng toàn hệ thống khoảng 15%, có thể điều chỉnh tăng hoặc giảm tùy diễn biến thực tế.
>
> **Giải thích thêm**
> - **NHNN**: NHNN là Ngân hàng Nhà nước Việt Nam, cơ quan quản lý nhà nước về tiền tệ và hoạt động ngân hàng.
> - **tăng trưởng tín dụng**: Tăng trưởng tín dụng là mức tăng của tổng số vốn các ngân hàng cho vay.
> - **toàn hệ thống**: Toàn hệ thống ở đây là tổng thể các tổ chức tín dụng trên cả nước.
>
> **Nguồn**
> - 12 nhiệm vụ trọng tâm của ngành Ngân hàng trong năm 2026 (kỳ 2026): https://thitruongtaichinhtiente.vn/12-nhiem-vu-trong-tam-cua-nganh-ngan-hang-trong-nam-2026-77347.html

**Your grade:** [ ] correct  [ ] partial  [ ] wrong

**Note:**

## 5. t14: Tháng 9/2026 lạm phát bao nhiêu và VN-Index tháng đó tăng hay giảm?

**Reference:** Specific month. Inflation 5.08% y/y (IMF and NSO agree: nso_report_2026_09_056); VN-Index Sep 2026 -3.47%. SQL: t14

**Answer:**

> **Trả lời ngắn**
> Tháng 9/2026, CPI tăng 0,62% so với tháng trước. VN-Index ở mức 1.768,62 điểm vào ngày 30/9, giảm 0,9% so với cuối năm 2025; báo cáo không nêu mức biến động so với tháng 8 nên chưa thể kết luận chỉ số tăng hay giảm riêng trong tháng 9.
>
> **Giải thích thêm**
> - **CPI**: CPI là chỉ số giá tiêu dùng, dùng để theo dõi mức thay đổi giá của một giỏ hàng hóa và dịch vụ tiêu biểu.
> - **so với tháng trước**: Đây là cách so sánh số liệu của tháng đang xét với số liệu của tháng liền trước.
> - **VN-Index**: VN-Index là chỉ số phản ánh biến động giá cổ phiếu trên sàn HOSE.
> - **so với cuối năm 2025**: Đây là cách so sánh số liệu với mức ghi nhận vào thời điểm cuối năm 2025.
>
> **Nguồn**
> - Báo cáo tình hình kinh tế – xã hội quý III và 9 tháng năm 2026 (kỳ 2026-09): https://www.nso.gov.vn/tin-tuc-thong-ke/2026/10/bao-cao-tinh-hinh-kinh-te-xa-hoi-quy-iii-va-9-thang-nam-2026/

**Your grade:** [ ] correct  [ ] partial  [ ] wrong

**Note:**

## 6. t22: Vốn FDI thực hiện tại Việt Nam trong 7 tháng đầu năm 2026 đạt bao nhiêu?

**Reference:** Doc nso_report_2026_07, chunk nso_report_2026_07_016: realized FDI seven months 2026 about 15.20 bn USD, +11.8% y/y.

**Answer:**

> **Trả lời ngắn**
> Trong 7 tháng đầu năm 2026, vốn đầu tư trực tiếp nước ngoài (FDI) thực hiện tại Việt Nam ước đạt 15,2 tỷ USD.
>
> **Giải thích thêm**
> - **Vốn đầu tư trực tiếp nước ngoài (FDI) thực hiện**: Là số vốn của nhà đầu tư nước ngoài đã được đưa vào triển khai các hoạt động đầu tư tại Việt Nam.
>
> **Nguồn**
> - Báo cáo tình hình kinh tế – xã hội tháng Bảy và 7 tháng năm 2026 (kỳ 2026-07): https://www.nso.gov.vn/bai-top/2026/08/bao-cao-tinh-hinh-kinh-te-xa-hoi-thang-bay-va-7-thang-nam-2026/

**Your grade:** [ ] correct  [ ] partial  [ ] wrong

**Note:**

## 7. t20: Năm 2023, tháng nào lạm phát so với cùng kỳ cao nhất?

**Reference:** Monthly ranking, IMF CPI. Reference: January 2023, 4.89% y/y. SQL: t20

**Answer:**

> **Trả lời ngắn**
> Theo dữ liệu CPI của IMF, tháng 1 năm 2023 có lạm phát so với cùng kỳ cao nhất, ở mức 4,89%.
>
> **Giải thích thêm**
> - **CPI**: CPI là chỉ số giá tiêu dùng, dùng để theo dõi mức thay đổi giá của một nhóm hàng hóa và dịch vụ.
> - **lạm phát so với cùng kỳ**: Đây là mức tăng giá so với cùng tháng của năm trước.
> - **IMF**: IMF là Quỹ Tiền tệ Quốc tế.
>
> **Nguồn**
> - Bảng `cpi_monthly`: chỉ số giá tiêu dùng (CPI) hằng tháng, nguồn IMF

**Your grade:** [ ] correct  [ ] partial  [ ] wrong

**Note:**

## 8. t38: Tin tức mới nhất về Vingroup hôm nay là gì?

**Reference:** News not in scope: decline; may offer VIC price data.

**Answer:**

> **Trả lời ngắn**
> Mình chưa có dữ liệu về tin tức Vingroup hôm nay, 17/11/2026; tài liệu được cung cấp không đề cập đến Vingroup hoặc tin tức của ngày này.

**Your grade:** [ ] correct  [ ] partial  [ ] wrong

**Note:**

## 9. t23: Báo cáo tháng 4/2026 nói gì về vận tải hành khách?

**Reference:** Doc nso_report_2026_04, chunk nso_report_2026_04_033: April passenger transport +17.3% (volume) and +15.8% (passenger-km) y/y; four months +15.0% and +12.7%; April about 509.5 million passengers.

**Answer:**

> **Trả lời ngắn**
> Theo báo cáo tháng 4/2026, vận tải hành khách đạt 509,5 triệu lượt khách vận chuyển, tăng 5,6% so với tháng trước; luân chuyển đạt 28,4 tỷ lượt khách.km, tăng 4,8%. So với cùng kỳ năm trước, vận chuyển tăng 17,3% và luân chuyển tăng 15,8%; tính chung bốn tháng đầu năm, hai chỉ tiêu lần lượt đạt 2.102,3 triệu lượt khách và 113,2 tỷ lượt khách.km.
>
> **Giải thích thêm**
> - **vận tải hành khách**: Hoạt động đưa hành khách di chuyển bằng các phương tiện vận tải.
> - **vận chuyển**: Số lượt khách được đưa đi bằng phương tiện vận tải.
> - **luân chuyển**: Khối lượng vận chuyển tính cả quãng đường hành khách đi được.
> - **lượt khách.km**: Đơn vị đo luân chuyển, tính số lượt khách nhân với quãng đường đi tính bằng kilômét.
> - **so với tháng trước**: So sánh kết quả tháng 4/2026 với tháng 3/2026.
> - **cùng kỳ năm trước**: So sánh với cùng khoảng thời gian của năm trước.
>
> **Nguồn**
> - Báo cáo tình hình kinh tế – xã hội tháng Tư và 4 tháng đầu năm 2026 (kỳ 2026-04): https://www.nso.gov.vn/bai-top/2026/05/bao-cao-tinh-hinh-kinh-te-xa-hoi-thang-tu-va-4-thang-dau-nam-2026/

**Your grade:** [ ] correct  [ ] partial  [ ] wrong

**Note:**

## 10. t30: Trong quý 1/2026 có bao nhiêu ngân hàng thương mại giảm lãi suất tiền gửi niêm yết?

**Reference:** Doc sbv_press_2026_q1, chunk sbv_press_2026_q1_004: 26 commercial banks cut listed deposit rates by about 0.1-0.5 pp, mostly 6-month and longer terms.

**Answer:**

> **Trả lời ngắn**
> Trong quý 1/2026, có 26 ngân hàng thương mại điều chỉnh giảm lãi suất tiền gửi niêm yết.
>
> **Giải thích thêm**
> - **ngân hàng thương mại**: Là ngân hàng cung cấp các dịch vụ như nhận tiền gửi và cho vay cho cá nhân, doanh nghiệp.
> - **lãi suất tiền gửi niêm yết**: Là mức lãi suất ngân hàng công bố cho khách hàng gửi tiền.
>
> **Nguồn**
> - Điều hành chính sách tiền tệ tiếp tục “hóa giải” thành công nhiều thách thức (kỳ 2026-Q1): https://vnba.org.vn/vi/dieu-hanh-chinh-sach-tien-te-tiep-tuc--hoa-giai--thanh-cong-nhieu-thach-thuc-21479.htm

**Your grade:** [ ] correct  [ ] partial  [ ] wrong

**Note:**
