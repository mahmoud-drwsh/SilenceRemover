# MP3 Manager SPA - User Stories (Compact 3-Row Layout)

## US-001: View Audio Items in Compact List
**As a** user viewing the audio list  
**I want** to see all items in a compact 3-row format without expanding  
**So that** I can quickly scan and manage many files without clicking

**Acceptance Criteria:**
- Each item shows in exactly 3 rows: Info Bar, Progress Bar, Title Textarea
- No accordion/expand behavior - all content always visible
- Row height is dynamic: 50px (base) + 20px (progress) + auto-grow (textarea)
- Maximum 4 items visible per mobile screen (vs 2-3 with accordion)

## US-002: Toggle Ready Status with Checkmark
**As a** user reviewing audio files  
**I want** to click a green checkmark icon to mark items ready/not-ready  
**So that** the action is immediately visible and takes minimal space

**Acceptance Criteria:**
- Display ☐ (empty box) when not ready, ✓ (green checkmark) when ready
- Single click toggles state without confirmation
- Visual feedback: checkmark turns green instantly, card border changes
- No text button needed - icon-only interaction
- Clicking ✓ makes it ☐ (unready), clicking ☐ makes it ✓ (ready)

## US-003: Delete with Confirmation Dialog
**As a** user managing audio files  
**I want** to confirm before moving items to trash  
**So that** I don't accidentally delete files

**Acceptance Criteria:**
- Clicking 🗑 (trash icon) shows browser `confirm()` dialog
- Dialog displays: "Move '{filename}' to trash?"
- [Cancel] → Close dialog, no action
- [OK] → Call API, remove card from DOM with fade animation
- For items already in trash view: "Delete '{filename}' permanently?"

## US-004: Auto-Resizing Title Textarea
**As a** user editing audio titles  
**I want** the title input to grow vertically as I type  
**So that** I can see multi-line titles without scrolling

**Acceptance Criteria:**
- Textarea starts at 1 line height (~24px)
- Auto-grows to max 4 lines (~96px) based on content
- No manual resize handle (resize: none)
- Debounced save: 500ms after typing stops
- Save shows spinner (⏳) next to textarea during API call
- On save success: brief checkmark indicator, then fade

## US-005: Always-Visible YouTube-Style Progress Bar
**As a** user playing audio files  
**I want** the progress bar always visible and interactive  
**So that** I can seek without expanding or playing first

**Acceptance Criteria:**
- Progress bar is Row 2, always rendered (not conditional on play state)
- Click anywhere on bar to seek to that position
- Drag circular handle (●) for precise scrubbing
- Bar fills blue (#2196F3) from left to current position
- Shows 0% fill when not played yet, updates during playback
- Current time / total duration display optional

## US-006: Play Audio Inline
**As a** user reviewing audio  
**I want** to click play and hear the audio immediately  
**So that** I can verify content without navigating

**Acceptance Criteria:**
- Click ▶ to start playback (spins while loading, then ▮▮ when playing)
- Audio plays in background using HTML5 Audio API
- Progress bar updates in real-time during playback
- Click ▮▮ to pause (returns to ▶)
- Only one audio plays at a time (stops previous if different file)
- Loading state shows spinner on play button if audio buffering

## US-007: Responsive Layout
**As a** user on mobile or desktop  
**I want** the layout to adapt to my screen size  
**So that** controls remain usable on all devices

**Acceptance Criteria:**
- Mobile (<480px): Icons only (no text on buttons), compact spacing
- Tablet/Desktop (>480px): Icons + text labels on buttons
- Touch targets minimum 44x44px for all interactive elements
- Horizontal scroll never occurs (wrap or truncate instead)

## US-008: Real-Time List Updates
**As a** user performing actions  
**I want** the list to update immediately without page refresh  
**So that** I have a smooth, app-like experience

**Acceptance Criteria:**
- Toggle ready: Card border changes instantly (green left border for ready)
- Move to trash: Card fades out and removes from current view
- Restore from trash: Card appears in appropriate view (ready/not-ready)
- Delete permanently: Card fades out and removes permanently
- Title edit: Textarea content saves in background, title display updates

## Technical Notes:
- Remove all `toggleExpand()` functions and `.expanded` CSS classes
- Replace `<input>` with `<textarea>` for title editing
- Add `autoResizeTextarea()` function: measures scrollHeight, sets height
- Add `confirmDelete()` wrapper for trash actions
- Progress bar click: calculate % from click position, seek audio
- All state changes use API client, optimistic UI updates
