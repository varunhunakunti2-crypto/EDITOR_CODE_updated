class MaskEditor {
    constructor() {
        this.canvas = document.getElementById('maskCanvas');
        this.ctx = this.canvas.getContext('2d');
        this.isDrawing = false;
        this.startX = 0;
        this.startY = 0;
        this.currentX = 0;
        this.currentY = 0;
        this.image = null;
        this.originalWidth = 0;
        this.originalHeight = 0;
        this.hasMask = false;
        
        this.initializeEvents();
    }

    initializeEvents() {
        this.canvas.addEventListener('mousedown', this.startDrawing.bind(this));
        this.canvas.addEventListener('mousemove', this.draw.bind(this));
        this.canvas.addEventListener('mouseup', this.stopDrawing.bind(this));
        this.canvas.addEventListener('mouseout', this.stopDrawing.bind(this));
        
        // Touch events for mobile
        this.canvas.addEventListener('touchstart', this.handleTouchStart.bind(this));
        this.canvas.addEventListener('touchmove', this.handleTouchMove.bind(this));
        this.canvas.addEventListener('touchend', this.handleTouchEnd.bind(this));
        
        document.getElementById('clearMask').addEventListener('click', this.clearMask.bind(this));
        document.getElementById('imageInput').addEventListener('change', this.handleImageUpload.bind(this));
        
        // Position buttons
        document.querySelectorAll('.position-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                this.handlePositionButton(e.target);
            });
        });
    }

    handlePositionButton(button) {
        // Remove active class from all buttons
        document.querySelectorAll('.position-btn').forEach(btn => {
            btn.classList.remove('active');
        });
        
        // Add active class to clicked button
        button.classList.add('active');
        
        const position = button.dataset.position;
        
        // Update position display
        const positionDisplay = position.split('_').map(word => 
            word.charAt(0).toUpperCase() + word.slice(1)
        ).join(' ');
        document.getElementById('currentPosition').textContent = positionDisplay;
        document.getElementById('currentPosition').className = 'ms-3 badge bg-success';
        
        // Set a special value to indicate auto-position
        document.getElementById('maskCoords').value = `auto_${position}`;
        this.hasMask = true;
        
        // Redraw with predefined position
        if (this.image) {
            this.drawPredefinedPosition(position);
        }
    }

    drawPredefinedPosition(position) {
        if (!this.image) return;
        
        // Clear and redraw image
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        this.ctx.drawImage(this.image, 0, 0, this.canvas.width, this.canvas.height);
        
        const scaleX = this.canvas.width / this.originalWidth;
        const scaleY = this.canvas.height / this.originalHeight;
        
        // Define positions similar to backend
        const positions = {
            'top_left': [50, 50, 200, 150],
            'top_right': [300, 50, 450, 150],
            'bottom_left': [50, 300, 200, 400],
            'bottom_right': [300, 300, 450, 400],
            'center_top': [180, 50, 330, 150],
            'center_bottom': [180, 300, 330, 400],
            'center': [180, 120, 330, 250]
        };
        
        const coords = positions[position] || positions['center'];
        const [x1, y1, x2, y2] = coords;
        
        // Draw the mask area
        this.ctx.strokeStyle = '#00ff00';
        this.ctx.lineWidth = 3;
        this.ctx.strokeRect(x1 * scaleX, y1 * scaleY, (x2 - x1) * scaleX, (y2 - y1) * scaleY);
        
        this.ctx.fillStyle = 'rgba(0, 255, 0, 0.2)';
        this.ctx.fillRect(x1 * scaleX, y1 * scaleY, (x2 - x1) * scaleX, (y2 - y1) * scaleY);
        
        // Add position text
        this.ctx.fillStyle = '#000000';
        this.ctx.font = '14px Arial';
        this.ctx.fillText(positionDisplay, x1 * scaleX + 5, y1 * scaleY + 20);
    }

    handleTouchStart(e) {
        e.preventDefault();
        const touch = e.touches[0];
        const mouseEvent = new MouseEvent('mousedown', {
            clientX: touch.clientX,
            clientY: touch.clientY
        });
        this.canvas.dispatchEvent(mouseEvent);
    }

    handleTouchMove(e) {
        e.preventDefault();
        const touch = e.touches[0];
        const mouseEvent = new MouseEvent('mousemove', {
            clientX: touch.clientX,
            clientY: touch.clientY
        });
        this.canvas.dispatchEvent(mouseEvent);
    }

    handleTouchEnd(e) {
        e.preventDefault();
        const mouseEvent = new MouseEvent('mouseup', {});
        this.canvas.dispatchEvent(mouseEvent);
    }

    handleImageUpload(event) {
        const file = event.target.files[0];
        if (file) {
            const reader = new FileReader();
            reader.onload = (e) => {
                this.image = new Image();
                this.image.onload = () => {
                    this.originalWidth = this.image.width;
                    this.originalHeight = this.image.height;
                    this.drawImage();
                };
                this.image.src = e.target.result;
                
                // Show preview
                const preview = document.getElementById('imagePreview');
                preview.innerHTML = `<img src="${e.target.result}" alt="Preview" class="img-fluid rounded">`;
            };
            reader.readAsDataURL(file);
        }
    }

    drawImage() {
        const container = this.canvas.parentElement;
        const maxWidth = container.clientWidth - 40;
        const maxHeight = 400;
        
        const scaleX = maxWidth / this.image.width;
        const scaleY = maxHeight / this.image.height;
        const scale = Math.min(scaleX, scaleY);
        
        this.canvas.width = this.image.width * scale;
        this.canvas.height = this.image.height * scale;
        
        this.ctx.drawImage(this.image, 0, 0, this.canvas.width, this.canvas.height);
    }

    getScaledCoordinates(clientX, clientY) {
        const rect = this.canvas.getBoundingClientRect();
        const x = (clientX - rect.left) * (this.originalWidth / this.canvas.width);
        const y = (clientY - rect.top) * (this.originalHeight / this.canvas.height);
        return { x, y };
    }

    startDrawing(e) {
        if (!this.image) {
            alert('Please upload an image first!');
            return;
        }
        
        // Clear position buttons when manually drawing
        document.querySelectorAll('.position-btn').forEach(btn => {
            btn.classList.remove('active');
        });
        
        document.getElementById('currentPosition').textContent = 'Manual Selection';
        document.getElementById('currentPosition').className = 'ms-3 badge bg-info';
        
        this.isDrawing = true;
        const coords = this.getScaledCoordinates(e.clientX, e.clientY);
        this.startX = coords.x;
        this.startY = coords.y;
        this.currentX = this.startX;
        this.currentY = this.startY;
    }

    draw(e) {
        if (!this.isDrawing || !this.image) return;
        
        const coords = this.getScaledCoordinates(e.clientX, e.clientY);
        this.currentX = coords.x;
        this.currentY = coords.y;
        
        this.redraw();
    }

    stopDrawing() {
        if (!this.isDrawing) return;
        
        this.isDrawing = false;
        this.saveMaskCoordinates();
        this.hasMask = true;
    }

    redraw() {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        this.ctx.drawImage(this.image, 0, 0, this.canvas.width, this.canvas.height);
        
        const scaleX = this.canvas.width / this.originalWidth;
        const scaleY = this.canvas.height / this.originalHeight;
        
        const x1 = Math.min(this.startX, this.currentX) * scaleX;
        const y1 = Math.min(this.startY, this.currentY) * scaleY;
        const width = Math.abs(this.currentX - this.startX) * scaleX;
        const height = Math.abs(this.currentY - this.startY) * scaleY;
        
        this.ctx.strokeStyle = '#ff0000';
        this.ctx.lineWidth = 3;
        this.ctx.strokeRect(x1, y1, width, height);
        
        this.ctx.fillStyle = 'rgba(255, 0, 0, 0.2)';
        this.ctx.fillRect(x1, y1, width, height);
    }

    saveMaskCoordinates() {
        const x1 = Math.min(this.startX, this.currentX);
        const y1 = Math.min(this.startY, this.currentY);
        const x2 = Math.max(this.startX, this.currentX);
        const y2 = Math.max(this.startY, this.currentY);
        
        const boundedX1 = Math.max(0, Math.min(x1, this.originalWidth));
        const boundedY1 = Math.max(0, Math.min(y1, this.originalHeight));
        const boundedX2 = Math.max(0, Math.min(x2, this.originalWidth));
        const boundedY2 = Math.max(0, Math.min(y2, this.originalHeight));
        
        const coords = `${Math.round(boundedX1)},${Math.round(boundedY1)},${Math.round(boundedX2)},${Math.round(boundedY2)}`;
        document.getElementById('maskCoords').value = coords;
    }

    clearMask() {
        // Clear position buttons
        document.querySelectorAll('.position-btn').forEach(btn => {
            btn.classList.remove('active');
        });
        
        document.getElementById('currentPosition').textContent = 'No selection - Using prompt detection';
        document.getElementById('currentPosition').className = 'ms-3 badge bg-warning';
        document.getElementById('maskCoords').value = '';
        this.hasMask = false;
        
        if (this.image) {
            this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
            this.ctx.drawImage(this.image, 0, 0, this.canvas.width, this.canvas.height);
        }
    }
}

// Initialize mask editor when page loads
document.addEventListener('DOMContentLoaded', function() {
    const maskEditor = new MaskEditor();
    
    // Upload area click handler
    document.getElementById('uploadArea').addEventListener('click', function() {
        document.getElementById('imageInput').click();
    });
    
    // Form validation
    document.getElementById('designForm').addEventListener('submit', function(e) {
        const imageInput = document.getElementById('imageInput').files[0];
        const prompt = document.querySelector('textarea[name="prompt"]').value.trim();
        
        if (!imageInput) {
            e.preventDefault();
            alert('Please upload an image!');
            return;
        }
        
        if (!prompt) {
            e.preventDefault();
            alert('Please enter a design prompt!');
            return;
        }
        
        // Show loading state
        const submitBtn = document.querySelector('button[type="submit"]');
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating...';
        submitBtn.disabled = true;
        
        // If no mask is selected, that's OK - we'll use auto-detection
        console.log('Form submitted with mask coords:', document.getElementById('maskCoords').value);
        console.log('Prompt:', prompt);
    });
    
    // Initialize with no selection message
    document.getElementById('currentPosition').textContent = 'No selection - Using prompt detection';
    document.getElementById('currentPosition').className = 'ms-3 badge bg-warning';
});