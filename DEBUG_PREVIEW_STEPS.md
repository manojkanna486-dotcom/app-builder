# Debug Test App Preview Issue - Manual Testing Guide

## Overview
The Test App preview is not showing despite the backend returning 112KB of HTML. I've added extensive debug logging to help identify the issue.

## Testing Steps

### 1. Start the Application
```bash
# Make sure both backend and frontend are running
# Backend should be on port 8000
# Frontend should be on port 3000
```

### 2. Open Browser DevTools
- Open Chrome/Firefox DevTools (F12)
- Go to the Console tab
- Clear any existing logs

### 3. Navigate to Test App
1. Go to http://localhost:3000
2. Find and click on "Test App" project (description: "Testing the app builder")
3. **IMPORTANT**: Watch the console for debug logs

### 4. Check Initial Load Logs
You should see these console logs when the page loads:

```javascript
// Expected logs:
"Preview response data: { html: '...' }"
"Preview response full: { data: {...}, status: 200, ... }"
"Initial preview load - HTML length: [number]"
"Initial preview load - HTML preview: [first 300 chars]"
"Initial preview load - previewHtml state before: [previous value]"

// If HTML is valid and > 100 chars:
"Setting previewHtml with [number] characters"

// If HTML is invalid or too short:
"Preview HTML not set - html exists: [true/false], length: [number]"

// During render:
"Render: viewMode = preview, previewHtml length = [number]"
```

### 5. What to Look For

#### Case A: Preview Shows (Success)
- You should see an iframe with the rendered app
- Console shows: `"Preview iframe loaded successfully"`
- `previewHtml length` should be > 100 (likely ~112000)

#### Case B: "No preview available" Message
This means one of these conditions failed:
1. **viewMode !== "preview"**: Check the render log - viewMode should be "preview"
2. **previewHtml.length <= 100**: Check the render log - length should be > 100
3. **previewHtml is null/undefined**: Check if HTML was received from API

#### Case C: Preview Shows But Broken/Empty
- Iframe renders but shows blank or error
- Check iframe console for JavaScript errors (see step 6)

### 6. Check Network Tab
1. Go to DevTools → Network tab
2. Find the request to: `/api/projects/[projectId]/preview`
3. Check:
   - **Status**: Should be 200
   - **Response**: Should contain `{"html": "<!DOCTYPE html>..."}`
   - **Size**: Should be ~112KB
   - **Headers**: Content-Type should be `application/json`

### 7. Check Iframe Errors (if preview shows but is blank)
If the iframe loads but shows nothing:
1. Right-click inside the preview area
2. Select "Inspect" or "Inspect Element"
3. In DevTools, look for iframe-specific errors in Console
4. Check if there are any Content Security Policy (CSP) errors

### 8. Try Manual Refresh
1. Click the "Refresh Preview" button (circular arrow icon)
2. Watch for these new console logs:
```javascript
"Refreshing preview for project: [projectId]"
"Refresh preview response: { html: '...' }"
"Refresh preview - HTML length: [number]"
"Setting preview HTML from refresh"
```

### 9. Try Opening in New Tab
1. Click the "Open in new tab" button (external link icon)
2. This opens `/api/projects/[projectId]/preview/live`
3. If this works but iframe doesn't, it's an iframe-specific issue

## Common Issues and Solutions

### Issue 1: HTML is undefined
**Symptoms**: Console shows `"Initial preview load - HTML length: 0"` or `"html exists: false"`

**Possible Causes**:
- Backend response format is wrong (not `{html: "..."}`)
- Network request failed silently
- CORS issue preventing response from being read

**Check**:
- Network tab shows successful response with HTML
- Backend logs show successful preview generation

### Issue 2: HTML is too short
**Symptoms**: Console shows `"HTML length: 50"` or similar (< 100)

**Possible Causes**:
- Backend is returning placeholder HTML
- No files found for the project
- Database query failing to retrieve files

**Check**:
- Backend logs: Look for "No files found for project"
- Check if Test App has any versions/files in database

### Issue 3: viewMode is not "preview"
**Symptoms**: Console shows `"Render: viewMode = code"`

**Possible Causes**:
- Tab switching logic is changing viewMode
- Initial state is being overridden
- URL parameter or localStorage setting different mode

**Check**:
- Click on "Preview" tab explicitly
- Check if there are any URL parameters affecting mode

### Issue 4: Iframe loads but shows blank
**Symptoms**: Console shows `"Preview iframe loaded successfully"` but nothing visible

**Possible Causes**:
- JavaScript errors in generated code
- CSS issues making content invisible
- React rendering errors in the app code

**Check**:
- Right-click in preview area → Inspect
- Look for errors in iframe's console
- Check if iframe actually has HTML content

## Collecting Debug Information

Please collect and report:

1. **All console logs** from initial page load
2. **Network request/response** for `/preview` endpoint
3. **Screenshot** of the preview area
4. **Any error messages** or warnings
5. **Browser and version** (Chrome 120, Firefox 115, etc.)

## Quick Diagnosis Checklist

- [ ] Backend running and accessible at localhost:8000
- [ ] Frontend running and accessible at localhost:3000
- [ ] Can navigate to Test App project page
- [ ] Console logs appear during page load
- [ ] Network request to `/preview` returns 200 status
- [ ] Response contains HTML (check Network tab)
- [ ] Console shows `"HTML length: [large number]"` not 0
- [ ] Console shows `"viewMode = preview"` during render
- [ ] Preview tab is selected (not Code tab)

## Expected Working Flow

When everything works correctly:

1. Page loads → `fetchProjectData()` called
2. API request to `/preview` returns `{"html": "<!DOCTYPE html>..."}` (~112KB)
3. Console: "HTML length: 114688" (example)
4. Console: "Setting previewHtml with 114688 characters"
5. Console: "Render: viewMode = preview, previewHtml length = 114688"
6. Iframe renders with `srcDoc` set to the HTML
7. Console: "Preview iframe loaded successfully"
8. App appears in preview pane

## Next Steps After Testing

After following these steps, please report:
- Which case (A, B, or C) occurred
- All relevant console logs
- Any errors or warnings
- Screenshots of the preview area and console

This will help identify exactly where the preview loading is failing.
