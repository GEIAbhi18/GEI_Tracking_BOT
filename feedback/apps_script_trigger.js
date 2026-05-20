/**
 * GEI Feedback Bot — Google Apps Script Trigger
 * ================================================
 * This script runs every 5 minutes via a time-based trigger.
 * It scans the MASTER sheet for complaints with Status = "Closed"
 * and Feedback Status = blank, then calls the bot API to initiate feedback.
 *
 * SETUP INSTRUCTIONS:
 * 1. Open Google Sheets → Extensions → Apps Script
 * 2. Paste this entire script
 * 3. Set BOT_URL and API_KEY below
 * 4. Run setupTrigger() once to create the 5-minute cron
 * 5. Authorize the script when prompted
 */

// ── CONFIGURATION ────────────────────────────────────────────────────────────
const BOT_URL = "https://gei-whatsapp-tracking-bot.onrender.com";
const API_KEY = "84kRVwKiBZrjJL2loRWXlhh_u6AJp_b6Wq_OKsbm250";  // Must match FEEDBACK_API_KEY in .env
const MASTER_SHEET_NAME = "MASTER";

// ── Column name mappings (adjust if your headers differ) ─────────────────────
const COL_COMPLAINT_ID    = "Complaint ID";
const COL_STATUS          = "Status";
const COL_FEEDBACK_STATUS = "Feedback Status";
const COL_FEEDBACK_SENT   = "Feedback Sent At";
const COL_CLIENT_PHONE    = "Client Phone";
const COL_CLIENT_NAME     = "Client Name";
const COL_UNIT_NO         = "Unit No";
const COL_COMPLAINT_NATURE = "Complaint Nature";
const COL_CLOSED_AT       = "Closed At";
const COL_BUILDING        = "Building";


/**
 * Main function — runs every 5 minutes via trigger.
 * Scans MASTER sheet and initiates feedback for newly closed complaints.
 */
function checkAndInitiateFeedback() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(MASTER_SHEET_NAME);
  
  if (!sheet) {
    Logger.log("ERROR: MASTER sheet not found");
    return;
  }
  
  const data = sheet.getDataRange().getValues();
  const headers = data[0];
  
  // Build column index map
  const colIdx = {};
  headers.forEach((h, i) => { colIdx[h.trim()] = i; });
  
  // Validate required columns exist
  const required = [COL_COMPLAINT_ID, COL_STATUS, COL_FEEDBACK_STATUS];
  for (const col of required) {
    if (colIdx[col] === undefined) {
      Logger.log(`ERROR: Column "${col}" not found in MASTER sheet headers`);
      return;
    }
  }
  
  let initiated = 0;
  
  for (let row = 1; row < data.length; row++) {
    const status = String(data[row][colIdx[COL_STATUS]] || "").trim().toLowerCase();
    const feedbackStatus = String(data[row][colIdx[COL_FEEDBACK_STATUS]] || "").trim();
    
    // Only process: Status = "Closed" AND Feedback Status is blank
    if (status !== "closed" || feedbackStatus !== "") {
      continue;
    }
    
    const complaintId = String(data[row][colIdx[COL_COMPLAINT_ID]] || "").trim();
    const clientPhone = String(data[row][colIdx[COL_CLIENT_PHONE]] || "").trim();
    const clientName  = String(data[row][colIdx[COL_CLIENT_NAME]] || "").trim();
    
    if (!complaintId || !clientPhone || !clientName) {
      Logger.log(`SKIP row ${row + 1}: missing complaintId, phone, or name`);
      continue;
    }
    
    const payload = {
      complaintId: complaintId,
      clientPhone: clientPhone,
      clientName: clientName,
      unitNo: String(data[row][colIdx[COL_UNIT_NO]] || "").trim(),
      complaintNature: String(data[row][colIdx[COL_COMPLAINT_NATURE]] || "").trim(),
      closedAt: String(data[row][colIdx[COL_CLOSED_AT]] || "").trim(),
      building: String(data[row][colIdx[COL_BUILDING]] || "").trim(),
    };
    
    // Call bot API
    const success = callFeedbackAPI(payload);
    
    if (success) {
      // Mark as "Sent" immediately to prevent duplicate triggers
      const sheetRow = row + 1; // 1-indexed
      const fbStatusCol = colIdx[COL_FEEDBACK_STATUS] + 1; // 1-indexed
      const fbSentCol = colIdx[COL_FEEDBACK_SENT] !== undefined 
                        ? colIdx[COL_FEEDBACK_SENT] + 1 
                        : null;
      
      sheet.getRange(sheetRow, fbStatusCol).setValue("Sent");
      
      if (fbSentCol) {
        const now = Utilities.formatDate(new Date(), "Asia/Kolkata", "yyyy-MM-dd HH:mm:ss");
        sheet.getRange(sheetRow, fbSentCol).setValue(now);
      }
      
      initiated++;
      Logger.log(`✅ Feedback initiated for ${complaintId} → ${clientPhone}`);
    } else {
      Logger.log(`❌ Failed to initiate feedback for ${complaintId}`);
    }
  }
  
  if (initiated > 0) {
    Logger.log(`Total feedback sessions initiated: ${initiated}`);
  }
}


/**
 * Call the bot's feedback initiation API.
 */
function callFeedbackAPI(payload) {
  const url = `${BOT_URL}/api/feedback/initiate`;
  
  const options = {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload),
    headers: {
      "X-API-Key": API_KEY,
    },
    muteHttpExceptions: true,
  };
  
  try {
    const response = UrlFetchApp.fetch(url, options);
    const code = response.getResponseCode();
    const body = response.getContentText();
    
    Logger.log(`API Response [${code}]: ${body}`);
    
    if (code === 200) {
      const result = JSON.parse(body);
      return result.status === "ok" || result.status === "queued";
    }
    
    return false;
  } catch (e) {
    Logger.log(`API call error: ${e.message}`);
    return false;
  }
}


/**
 * One-time setup: Creates a 5-minute time-based trigger.
 * Run this function ONCE from the Apps Script editor.
 */
function setupTrigger() {
  // Remove existing triggers for this function
  const triggers = ScriptApp.getProjectTriggers();
  for (const trigger of triggers) {
    if (trigger.getHandlerFunction() === "checkAndInitiateFeedback") {
      ScriptApp.deleteTrigger(trigger);
    }
  }
  
  // Create new 5-minute trigger
  ScriptApp.newTrigger("checkAndInitiateFeedback")
    .timeBased()
    .everyMinutes(5)
    .create();
  
  Logger.log("✅ 5-minute trigger created for checkAndInitiateFeedback");
}


/**
 * Manual test: Trigger feedback for a specific complaint.
 * Edit the payload below and run from Apps Script editor.
 */
function testFeedbackTrigger() {
  const testPayload = {
    complaintId: "B1-00032",
    clientPhone: "7982990892",
    clientName: "Sumit Singh Rawat",
    unitNo: "301",
    complaintNature: "BMS",
    closedAt: "2026-05-18 09:40",
    building: "GEBB1",
  };
  
  const success = callFeedbackAPI(testPayload);
  Logger.log(success ? "✅ Test successful" : "❌ Test failed");
}
