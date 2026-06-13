# HTMX Guidelines for Server-Rendered Applications

## Core Philosophy

HTMX enables building modern web applications with minimal JavaScript by leveraging hypermedia as the engine of application state (HATEOAS). This guide provides best practices for using HTMX with FastAPI and similar server-side frameworks.

## 1. Application Architecture

### 1.1 Server-Side Rendering First

**DO:** Use server-side rendering for all content that can be rendered on the server.

```python
# Good: Detect HTMX requests and return appropriate response
async def get_page(
    request: Request,
    hx_request: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    is_htmx = bool(hx_request)
    
    if is_htmx:
        # Return only the content that needs updating
        return templates.TemplateResponse(
            "partials/content.html",
            {"request": request, "data": data}
        )
    else:
        # Return full page for initial load
        return templates.TemplateResponse(
            "full_page.html",
            {"request": request, "data": data}
        )
```

**DON'T:** Use JavaScript to fetch and render content that could be server-rendered.

```javascript
// Bad: Unnecessary client-side rendering
fetch('/api/data')
    .then(response => response.json())
    .then(data => {
        document.getElementById('content').innerHTML = renderTemplate(data);
    });
```

### 1.2 Route Design for HTMX

**DO:** Design routes that can handle both full page loads and partial updates.

```python
# Good: Flexible route handler
def get_template_response(
    templates: Jinja2Templates,
    is_htmx: bool,
    full_page_template: str,
    partial_templates: Dict[str, str],
    context: dict
) -> Response:
    if is_htmx:
        # Return specific partial based on hx-target
        target = context.get("hx_target", "content")
        template = partial_templates.get(target, partial_templates["content"])
        return templates.TemplateResponse(template, context)
    return templates.TemplateResponse(full_page_template, context)
```

**Scoring Metric:** Routes should support both HTMX and non-HTMX requests (Score: 0-10)

## 2. HTMX Usage Patterns

### 2.1 Form Handling

**DO:** Use HTMX for form submissions with proper indicators and error handling.

```html
<!-- Good: Complete form pattern -->
<form hx-post="/submit"
      hx-target="#result"
      hx-swap="outerHTML"
      hx-indicator="#spinner"
      hx-encoding="multipart/form-data"
      @htmx:before-request="this.querySelectorAll('input').forEach(i => i.disabled = true)"
      @htmx:after-request="this.querySelectorAll('input').forEach(i => i.disabled = false)">
    
    <input type="text" name="field" required>
    
    <button type="submit" class="btn">
        Submit
        <span id="spinner" class="htmx-indicator">
            <i class="loading loading-spinner"></i>
        </span>
    </button>
</form>

<div id="result">
    <!-- Server returns this div with success/error message -->
</div>
```

**DON'T:** Mix HTMX with traditional form JavaScript.

```html
<!-- Bad: Mixing paradigms -->
<form hx-post="/submit" onsubmit="return validateForm()">
    <!-- This creates confusion about what handles the submission -->
</form>
```

### 2.2 Dynamic Content Loading

**DO:** Use appropriate HTMX triggers for content loading.

```html
<!-- Good: Various loading patterns -->

<!-- Load on page visibility -->
<div hx-get="/expensive-content"
     hx-trigger="revealed"
     hx-swap="innerHTML">
    <div class="skeleton">Loading...</div>
</div>

<!-- Load based on user interaction with debouncing -->
<input type="search"
       name="query"
       hx-get="/search"
       hx-trigger="keyup changed delay:500ms"
       hx-target="#search-results">

<!-- Load based on custom events -->
<div hx-get="/related-content"
     hx-trigger="content-selected from:body"
     hx-swap="innerHTML">
</div>
```

**Scoring Metric:** Appropriate trigger usage (revealed, delay, throttle) (Score: 0-10)

### 2.3 Navigation and History

**DO:** Manage browser history appropriately.

```html
<!-- Good: Update URL for navigational changes -->
<a hx-get="/page/2"
   hx-target="#content"
   hx-push-url="true"
   class="pagination-link">
    Page 2
</a>

<!-- Good: Don't update URL for UI state changes -->
<button hx-post="/toggle-panel"
        hx-target="#panel"
        hx-swap="outerHTML">
    Toggle Panel
</button>
```

## 3. JavaScript Usage Guidelines

### 3.1 AlpineJS for Client-Side Behavior

**DO:** Use AlpineJS for client-side state and interactions.

```html
<!-- Good: Alpine for UI state -->
<div x-data="{ 
    isOpen: false,
    selectedItems: [],
    toggleItem(id) {
        const index = this.selectedItems.indexOf(id);
        if (index > -1) {
            this.selectedItems.splice(index, 1);
        } else {
            this.selectedItems.push(id);
        }
    }
}">
    <button @click="isOpen = !isOpen">Toggle Menu</button>
    
    <div x-show="isOpen" x-transition>
        <!-- Menu content -->
    </div>
    
    <!-- HTMX form that uses Alpine state -->
    <form hx-post="/bulk-action"
          hx-vals='js:{items: Alpine.$data(this).selectedItems}'>
        <button>Process Selected</button>
    </form>
</div>
```

**DON'T:** Embed JavaScript in templates for UI logic.

```html
<!-- Bad: Inline JavaScript -->
<button onclick="document.getElementById('menu').style.display = 'block'">
    Show Menu
</button>

<script>
    function toggleMenu() {
        // UI logic should be in Alpine
    }
</script>
```

### 3.2 HTMX and Alpine Integration

**DO:** Use HTMX events with Alpine for complex workflows.

```html
<!-- Good: Coordinated HTMX and Alpine -->
<form x-data="{ isSubmitting: false, errors: {} }"
      hx-post="/api/submit"
      hx-target="#result"
      @htmx:before-request="isSubmitting = true; errors = {}"
      @htmx:after-request="isSubmitting = false"
      @htmx:response-error="errors = JSON.parse($event.detail.xhr.response)">
    
    <input type="text" 
           name="email"
           :class="{ 'input-error': errors.email }">
    <span x-show="errors.email" x-text="errors.email" class="error"></span>
    
    <button type="submit" :disabled="isSubmitting">
        <span x-show="!isSubmitting">Submit</span>
        <span x-show="isSubmitting">Processing...</span>
    </button>
</form>
```

**Scoring Metric:** Proper separation of concerns between HTMX and Alpine (Score: 0-10)

## 4. Real-Time Features

### 4.1 WebSocket Integration

**DO:** Use HTMX WebSocket extension for real-time updates.

```html
<!-- Good: Chat implementation with WebSockets -->
<div id="chat-container"
     hx-ext="ws"
     ws-connect="/ws/chat/{{ room_id }}">
    
    <div id="messages">
        <!-- Messages populated by server via WebSocket -->
    </div>
    
    <form ws-send>
        <input name="message" type="text">
        <button type="submit">Send</button>
    </form>
</div>
```

**DON'T:** Implement custom WebSocket handling when HTMX can handle it.

```javascript
// Bad: Custom WebSocket implementation
const ws = new WebSocket('/ws/chat');
ws.onmessage = (event) => {
    document.getElementById('messages').innerHTML += event.data;
};
```

## 5. User Feedback and Micro-interactions

### 5.1 Loading States

**DO:** Always provide visual feedback for actions.

```html
<!-- Good: Multiple feedback mechanisms -->
<button hx-post="/action"
        hx-indicator="#global-spinner"
        class="btn"
        :disabled="isProcessing"
        @htmx:before-request="isProcessing = true"
        @htmx:after-request="isProcessing = false">
    <span x-show="!isProcessing">Save</span>
    <span x-show="isProcessing">Saving...</span>
</button>

<!-- Global spinner -->
<div id="global-spinner" class="htmx-indicator">
    <div class="spinner"></div>
</div>
```

### 5.2 Toast Notifications

**DO:** Implement server-driven notifications.

```html
<!-- Good: Server sends toast via HTMX -->
<div id="toast-container">
    <!-- Server response includes toast HTML -->
</div>

<!-- In response -->
<div hx-swap-oob="afterbegin:#toast-container">
    <div class="toast toast-success" x-data x-init="setTimeout(() => $el.remove(), 3000)">
        Operation completed successfully!
    </div>
</div>
```

## 6. Performance Best Practices

### 6.1 Request Optimization

**DO:** Use appropriate swap strategies and targets.

```html
<!-- Good: Precise targeting -->
<tr hx-delete="/item/{{ item.id }}"
    hx-target="closest tr"
    hx-swap="outerHTML swap:1s"
    hx-confirm="Delete this item?">
    <td>{{ item.name }}</td>
    <td><button>Delete</button></td>
</tr>
```

### 6.2 Debouncing and Throttling

**DO:** Prevent excessive requests.

```html
<!-- Good: Search with debouncing -->
<input type="search"
       hx-get="/search"
       hx-trigger="keyup changed delay:500ms, search"
       hx-target="#results"
       name="q">

<!-- Good: Scroll with throttling -->
<div hx-get="/more"
     hx-trigger="scrolled throttle:1s"
     hx-swap="afterend">
</div>
```

## 7. Error Handling

### 7.1 Graceful Degradation

**DO:** Ensure forms work without JavaScript.

```html
<!-- Good: Progressive enhancement -->
<form method="POST" action="/submit"
      hx-post="/submit"
      hx-target="#result">
    <!-- Form works with or without HTMX -->
    <input type="text" name="data" required>
    <button type="submit">Submit</button>
</form>
```

### 7.2 Error States

**DO:** Handle errors at both HTMX and Alpine levels.

```html
<!-- Good: Comprehensive error handling -->
<div x-data="{ error: null }"
     @htmx:response-error="error = 'Failed to load content'">
    
    <div hx-get="/content"
         hx-trigger="load"
         hx-target="this">
        Loading...
    </div>
    
    <div x-show="error" class="alert alert-error">
        <span x-text="error"></span>
        <button @click="error = null; htmx.trigger($el.previousElementSibling, 'load')">
            Retry
        </button>
    </div>
</div>
```

## Scoring Rubric

### A. Architecture (30 points)
- [ ] Server-side rendering for all possible content (10 points)
- [ ] Routes handle both HTMX and non-HTMX requests (10 points)
- [ ] Clear separation between server and client concerns (10 points)

### B. HTMX Usage (25 points)
- [ ] Appropriate use of HTMX attributes (5 points)
- [ ] Proper trigger usage with delays/throttling (5 points)
- [ ] Correct swap strategies and targets (5 points)
- [ ] URL management with hx-push-url (5 points)
- [ ] Loading indicators on all actions (5 points)

### C. JavaScript Discipline (20 points)
- [ ] AlpineJS for all client-side state (10 points)
- [ ] No inline JavaScript or onclick handlers (5 points)
- [ ] No unnecessary client-side rendering (5 points)

### D. User Experience (15 points)
- [ ] Visual feedback for all actions (5 points)
- [ ] Graceful error handling (5 points)
- [ ] Progressive enhancement (5 points)

### E. Performance (10 points)
- [ ] Request debouncing/throttling where appropriate (5 points)
- [ ] Efficient DOM updates with proper targets (5 points)

**Total Score: /100**

## Conclusion

Following these guidelines ensures a maintainable, performant application that leverages the full power of hypermedia-driven architecture. The key is to trust the server as the source of truth and use HTMX to efficiently update the UI based on server responses, while using AlpineJS sparingly for genuinely client-side interactions.