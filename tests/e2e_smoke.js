const { chromium } = require("playwright");

async function waitForText(page, text) {
  await page.getByText(text, { exact: false }).first().waitFor({ timeout: 45000 });
}

async function login(page, username, password, expectedText) {
  await page.getByLabel("ชื่อผู้ใช้").fill(username);
  await page.getByLabel("รหัสผ่าน").fill(password);
  await page.getByRole("button", { name: "เข้าสู่ระบบ" }).click();
  await waitForText(page, expectedText);
}

(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));

  await page.goto("http://localhost:8502");
  await waitForText(page, "เข้าสู่ระบบแจ้งข้อมูลค่าที่พัก");
  await page.screenshot({ path: "audit/00_login.png", fullPage: true });

  await login(page, "admin", "area2", "ศูนย์จัดการข้อมูลค่าที่พัก");
  await page.getByText("โรงแรม", { exact: true }).click();
  await page.getByLabel("ชื่อโรงแรม *").fill("โรงแรมทดสอบระบบ");
  await page.getByLabel("อำเภอ/เขต").fill("เมือง");
  await page.getByLabel("จังหวัด *").fill("สกลนคร");
  await page.getByRole("button", { name: "เพิ่มโรงแรม" }).click();
  await waitForText(page, "เพิ่มโรงแรมเรียบร้อยแล้ว");
  await page.screenshot({ path: "audit/01_admin_hotel.png", fullPage: true });

  await page.getByRole("button", { name: "ออกจากระบบ" }).click();
  await login(page, "staff", "123456", "แจ้งข้อมูลการเข้าพัก");
  await page.getByLabel("รหัสพนักงาน *").fill("TEST001");
  await page.getByLabel("รหัสพนักงาน *").press("Enter");
  await page.waitForTimeout(2000);
  await page.getByLabel("เลขที่อนุมัติ SA/BT *").fill("SA202610050001");
  await page.getByLabel("เลขที่อนุมัติ SA/BT *").press("Enter");
  await waitForText(page, "SA: วันที่เริ่มต้นและสิ้นสุดต้องเป็นวันเดียวกัน");
  await page.getByLabel("ชื่อพนักงาน *").fill("พนักงานทดสอบ");
  await page.getByLabel("สาขาที่ประจำ *").fill("TEST_SP-ต้นทาง");
  await page.getByLabel("สาขาที่เข้าช่วยเหลือ *").fill("TEST_DC-ปลายทาง");
  await page.getByLabel("เลขห้อง *").fill("101");
  await page.getByLabel("ยืนยันว่าข้อมูลโรงแรม ห้อง และช่วงวันที่ถูกต้อง").check({ force: true });
  await page.screenshot({ path: "audit/02_employee_form.png", fullPage: true });
  await page.getByRole("button", { name: "บันทึกข้อมูลการเข้าพัก" }).click();
  await waitForText(page, "บันทึกข้อมูลเรียบร้อยแล้ว");

  await page.getByRole("button", { name: "ออกจากระบบ" }).click();
  await login(page, "admin", "area2", "ศูนย์จัดการข้อมูลค่าที่พัก");
  await page.getByText("ใบเสร็จ", { exact: true }).click();
  await page.getByLabel("เลขที่ใบเสร็จ *").fill("RC-TEST-001");
  await page.getByLabel("ยอดใบเสร็จรวม VAT (บาท) *").fill("650");
  await page.getByRole("button", { name: "บันทึกใบเสร็จ" }).click();
  await waitForText(page, "บันทึกใบเสร็จแล้ว");

  await page.getByText("จัดห้องและราคา", { exact: true }).click();
  await waitForText(page, "จัดห้อง ผู้พักร่วม และราคาเบิก");
  await page.getByLabel("พนักงานที่พักห้องนี้ (สูงสุด 2 คน)").click();
  await page.getByText(/พนักงานทดสอบ \(TEST001\)/).click();
  await page.getByLabel("ราคาห้องต่อคืนรวม VAT *").fill("650");
  await page.getByLabel("เหตุผลพักคนเดียว").fill("เดินทางช่วยเหลือเพียงคนเดียว");
  await page.screenshot({ path: "audit/03_admin_room_claim.png", fullPage: true });
  await page.getByRole("button", { name: "บันทึกรายการห้อง" }).click();
  await waitForText(page, "รอ Mail อนุมัติ");

  await page.getByText("ส่งออก", { exact: true }).click();
  await waitForText(page, "ดาวน์โหลด Excel สรุป");
  await page.screenshot({ path: "audit/04_export.png", fullPage: true });

  await page.getByRole("button", { name: "ออกจากระบบ" }).click();
  await login(page, "staff", "123456", "แจ้งข้อมูลการเข้าพัก");
  await page.getByText("แก้ไขข้อมูล", { exact: true }).click();
  await page.getByLabel("รหัสพนักงานของรายการที่ต้องการแก้ไข *").fill("TEST001");
  await page.getByLabel("รหัสพนักงานของรายการที่ต้องการแก้ไข *").press("Enter");
  await waitForText(page, "รายการนี้ถูก Admin นำไปทำเบิกแล้ว");
  await page.screenshot({ path: "audit/05_locked_submission.png", fullPage: true });

  console.log(JSON.stringify({ pageErrors: errors, checks: { login: true, hotel: true, submission: true, receipt: true, roomClaim: true, lockedEdit: true, export: true } }, null, 2));
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});

