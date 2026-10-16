/**
 * TourMate Centralized Mobile API Client
 * Manages JWT tokens, automatic Bearer headers, centralized error handling, and session management.
 */

const _memoryStorage = {};

const TourMateAPI = {
    TOKEN_KEY: 'tourmate_token',
    USER_KEY: 'tourmate_user',
    API_BASE: '/api/v1',

    _getItem(key) {
        try {
            return localStorage.getItem(key);
        } catch (e) {
            return _memoryStorage[key] || null;
        }
    },

    _setItem(key, val) {
        try {
            localStorage.setItem(key, val);
        } catch (e) {
            _memoryStorage[key] = val;
        }
    },

    _removeItem(key) {
        try {
            localStorage.removeItem(key);
        } catch (e) {
            delete _memoryStorage[key];
        }
    },

    getToken() {
        let token = this._getItem(this.TOKEN_KEY);
        if (!token || token === 'undefined' || token === 'null' || token === '') {
            try {
                const match = document.cookie.match(new RegExp('(^| )tourmate_token=([^;]+)'));
                if (match && match[2]) {
                    token = decodeURIComponent(match[2]);
                    this._setItem(this.TOKEN_KEY, token);
                }
            } catch (e) {}
        }
        return (token && token !== 'undefined' && token !== 'null') ? token : null;
    },

    getUser() {
        try {
            let raw = this._getItem(this.USER_KEY);
            if (!raw) {
                try {
                    const match = document.cookie.match(new RegExp('(^| )tourmate_user=([^;]+)'));
                    if (match && match[2]) {
                        raw = decodeURIComponent(match[2]);
                        this._setItem(this.USER_KEY, raw);
                    }
                } catch (e) {}
            }
            return raw ? JSON.parse(raw) : null;
        } catch (e) {
            return null;
        }
    },

    setAuth(token, user) {
        if (token) {
            this._setItem(this.TOKEN_KEY, token);
            try {
                document.cookie = `tourmate_token=${encodeURIComponent(token)}; path=/; max-age=604800; SameSite=Lax`;
            } catch (e) {}
        }
        if (user) {
            this._setItem(this.USER_KEY, JSON.stringify(user));
            try {
                document.cookie = `tourmate_user=${encodeURIComponent(JSON.stringify(user))}; path=/; max-age=604800; SameSite=Lax`;
            } catch (e) {}
        }
    },

    clearAuth() {
        this._removeItem(this.TOKEN_KEY);
        this._removeItem(this.USER_KEY);
        try {
            document.cookie = 'tourmate_token=; path=/; max-age=0; SameSite=Lax';
            document.cookie = 'tourmate_user=; path=/; max-age=0; SameSite=Lax';
        } catch (e) {}
    },

    isAuthenticated() {
        return !!this.getToken();
    },

    ensureAuth() {
        if (!this.isAuthenticated()) {
            const nextPath = encodeURIComponent(window.location.pathname + window.location.search);
            window.location.href = `/login?next=${nextPath}`;
            return false;
        }
        return true;
    },

    async rawRequest(path, options = {}) {
        const url = `${this.API_BASE}${path}`;
        const headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            ...(options.headers || {})
        };

        const token = this.getToken();
        if (token && !headers['Authorization']) {
            headers['Authorization'] = `Bearer ${token}`;
        }

        const response = await fetch(url, {
            ...options,
            headers
        });

        if (response.status === 401) {
            this.clearAuth();
            window.showToast('সেশন শেষ হয়ে গেছে, দয়া করে আবার লগইন করুন', 'error');
            setTimeout(() => {
                window.location.href = '/login';
            }, 1000);
            throw new Error('Unauthorized');
        }

        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            const message = data.detail || (data.errors && data.errors[0]?.msg) || 'অনাকাঙ্ক্ষিত সমস্যা হয়েছে!';
            throw new Error(message);
        }

        return data;
    },

    async request(path, options = {}) {
        const method = (options.method || 'GET').toUpperCase();
        const isMutating = ['POST', 'PUT', 'DELETE', 'PATCH'].includes(method);

        // If user is currently offline:
        if (!navigator.onLine) {
            if (isMutating) {
                TourMateSync.addToQueue({ path, options });
                window.showToast('অফলাইন মোড: এন্ট্রিটি ফোনে জমা হলো। নেট পেলেই সিঙ্ক হবে।', 'info');
                return { success: true, offline: true };
            } else {
                console.warn('Device is offline: reading from local cache for', path);
                const offlineErr = new Error('Offline');
                offlineErr.isOffline = true;
                throw offlineErr;
            }
        }

        try {
            return await this.rawRequest(path, options);
        } catch (error) {
            // If network fetch fails on mutating actions, queue for background sync
            if (isMutating && (!navigator.onLine || error.name === 'TypeError' || (error.message && error.message.includes('fetch')))) {
                TourMateSync.addToQueue({ path, options });
                window.showToast('নেটওয়ার্ক নেই: এন্ট্রিটি ফোনে সংরক্ষণ করা হলো। সংযোগ পেলে সিঙ্ক হবে।', 'info');
                return { success: true, offline: true };
            }
            // For all GET requests, never show toast error - quietly fall back to local cached state
            if (!isMutating) {
                console.warn('GET request failed (offline or network error); relying on local cached state:', path, error.message);
                throw error;
            }
            if (error.message !== 'Unauthorized' && error.message !== 'Offline') {
                window.showToast(error.message, 'error');
            }
            throw error;
        }
    },

    // Authentication Endpoints
    async authGoogle(idToken) {
        const res = await this.request('/auth/google', {
            method: 'POST',
            body: JSON.stringify({ id_token: idToken })
        });
        this.setAuth(res.access_token, res.user);
        return res;
    },

    async authDemo() {
        const res = await this.request('/auth/demo', {
            method: 'POST'
        });
        this.setAuth(res.access_token, res.user);
        return res;
    },

    logout() {
        this.clearAuth();
        window.location.href = '/login';
    },

    async updateProfile(payload) {
        const user = await this.request('/auth/profile', {
            method: 'PUT',
            body: JSON.stringify(payload)
        });
        this.setAuth(null, user);
        return user;
    },

    // Tours Endpoints
    async getTours() {
        return this.request('/tours/');
    },

    async createTour(payload) {
        return this.request('/tours/', {
            method: 'POST',
            body: JSON.stringify(payload)
        });
    },

    async updateTour(tourId, payload) {
        return this.request(`/tours/${tourId}`, {
            method: 'PUT',
            body: JSON.stringify(payload)
        });
    },

    async deleteTour(tourId) {
        return this.request(`/tours/${tourId}`, {
            method: 'DELETE'
        });
    },

    async toggleArchiveTour(tourId) {
        return this.request(`/tours/${tourId}/toggle-archive`, {
            method: 'POST'
        });
    },

    async getDashboard(tourId) {
        return this.request(`/tours/${tourId}/dashboard`);
    },

    async shareTour(tourId, payload) {
        return this.request(`/tours/${tourId}/share`, {
            method: 'POST',
            body: JSON.stringify(payload)
        });
    },

    async updateMember(tourId, memberId, payload) {
        return this.request(`/tours/${tourId}/members/${memberId}`, {
            method: 'PUT',
            body: JSON.stringify(payload)
        });
    },

    async deleteMember(tourId, memberId) {
        return this.request(`/tours/${tourId}/members/${memberId}`, {
            method: 'DELETE'
        });
    },

    // Deposits Endpoints
    async addDeposit(tourId, payload) {
        return this.request(`/tours/${tourId}/deposits`, {
            method: 'POST',
            body: JSON.stringify(payload)
        });
    },

    async updateDeposit(tourId, depositId, payload) {
        return this.request(`/tours/${tourId}/deposits/${depositId}`, {
            method: 'PUT',
            body: JSON.stringify(payload)
        });
    },

    async deleteDeposit(tourId, depositId) {
        return this.request(`/tours/${tourId}/deposits/${depositId}`, {
            method: 'DELETE'
        });
    },

    // Expenses Endpoints
    async addExpense(tourId, payload) {
        return this.request(`/tours/${tourId}/expenses`, {
            method: 'POST',
            body: JSON.stringify(payload)
        });
    },

    async updateExpense(tourId, expenseId, payload) {
        return this.request(`/tours/${tourId}/expenses/${expenseId}`, {
            method: 'PUT',
            body: JSON.stringify(payload)
        });
    },

    async deleteExpense(tourId, expenseId) {
        return this.request(`/tours/${tourId}/expenses/${expenseId}`, {
            method: 'DELETE'
        });
    },

    async getExpenseSuggestions(tourId) {
        return this.request(`/tours/${tourId}/expenses/suggestions`);
    },

    // Settlement Endpoints
    async getSettlement(tourId) {
        return this.request(`/tours/${tourId}/settlement`);
    },

    // Collaboration & Activity Endpoints
    async addComment(tourId, expenseId, payload) {
        return this.request(`/tours/${tourId}/expenses/${expenseId}/comments`, {
            method: 'POST',
            body: JSON.stringify(payload)
        });
    },

    async getActivity(tourId) {
        return this.request(`/tours/${tourId}/activity`);
    },

    // Feedback & Suggestions Endpoints
    async submitFeedback(payload) {
        return this.request('/feedback/', {
            method: 'POST',
            body: JSON.stringify(payload)
        });
    },

    async getFeedbacks() {
        return this.request('/feedback/');
    }
};

window.showToast = function(message, type = 'success') {
    window.dispatchEvent(new CustomEvent('tourmate-toast', {
        detail: { message, type }
    }));
};

/**
 * TourMate Offline Queue & Auto-Sync Engine
 * Captures mutations when network is absent or unstable, keeps queue in localStorage,
 * and seamlessly pushes to Neon Cloud DB when network restores.
 */
const TourMateSync = {
    QUEUE_KEY: 'tourmate_offline_queue',
    isOnline: typeof navigator !== 'undefined' ? navigator.onLine : true,
    isSyncing: false,

    getQueue() {
        try {
            return JSON.parse(localStorage.getItem(this.QUEUE_KEY) || '[]');
        } catch (e) {
            return [];
        }
    },

    saveQueue(queue) {
        localStorage.setItem(this.QUEUE_KEY, JSON.stringify(queue));
        this.notify();
    },

    addToQueue(item) {
        const queue = this.getQueue();
        queue.push({
            id: 'sync_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6),
            ...item,
            timestamp: new Date().toISOString()
        });
        this.saveQueue(queue);
    },

    notify() {
        window.dispatchEvent(new CustomEvent('tourmate-sync-status', {
            detail: {
                isOnline: this.isOnline,
                pendingCount: this.getQueue().length,
                isSyncing: this.isSyncing
            }
        }));
    },

    async syncNow() {
        if (!navigator.onLine || this.isSyncing) return;
        const queue = this.getQueue();
        if (queue.length === 0) return;

        this.isSyncing = true;
        this.notify();

        let successCount = 0;
        const remaining = [];

        for (const item of queue) {
            try {
                await TourMateAPI.rawRequest(item.path, item.options);
                successCount++;
            } catch (err) {
                console.error('Failed to sync offline item:', item, err);
                remaining.push(item);
            }
        }

        this.isSyncing = false;
        this.saveQueue(remaining);

        if (successCount > 0) {
            window.showToast(`✅ ক্লাউড ডাটাবেজে ${successCount}টি অফলাইন এন্ট্রি সিঙ্ক হয়েছে!`, 'success');
            window.dispatchEvent(new CustomEvent('tourmate-synced-refresh'));
        }
    },

    init() {
        window.addEventListener('online', () => {
            this.isOnline = true;
            this.notify();
            window.showToast('🌐 ইন্টারনেট ফিরে এসেছে! ক্লাউড সিঙ্ক শুরু হচ্ছে...', 'info');
            this.syncNow();
        });

        window.addEventListener('offline', () => {
            this.isOnline = false;
            this.notify();
            window.showToast('📡 আপনি অফলাইনে আছেন। সকল নতুন এন্ট্রি ফোনে সংরক্ষিত থাকবে।', 'info');
        });

        // Trigger on load if online and has pending items
        if (typeof navigator !== 'undefined' && navigator.onLine && this.getQueue().length > 0) {
            setTimeout(() => this.syncNow(), 1500);
        }
    }
};

if (typeof window !== 'undefined') {
    window.TourMateSync = TourMateSync;
    TourMateSync.init();
}
