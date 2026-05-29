<template>
    <!-- Floating toggle button -->
    <button
        class="contact-fab"
        :aria-label="open ? 'Minimize contact form' : 'Open contact form'"
        :aria-expanded="open"
        @click="toggle"
    >
        <!-- Minimize when open, question mark when closed -->
        <img
            v-if="open"
            src="../assets/minimize-2.svg"
            width="28"
            height="28"
            alt=""
        />
        <img
            v-else
            src="../assets/circle-question-mark.svg"
            width="28"
            height="28"
            alt=""
        />
    </button>

    <!-- Popup panel -->
    <transition name="contact-pop">
        <div v-if="open" class="contact-panel">
            <h2 class="contact-title">Contact Us</h2>

            <!-- Form state -->
            <form
                v-if="!sent"
                class="contact-form"
                @submit.prevent="submit"
            >
                <input
                    v-model.trim="form.name"
                    class="contact-input"
                    type="text"
                    placeholder="Name"
                    :disabled="sending"
                />
                <input
                    v-model.trim="form.email"
                    class="contact-input"
                    type="email"
                    placeholder="Email"
                    :disabled="sending"
                />
                <input
                    v-model.trim="form.phone"
                    class="contact-input"
                    type="tel"
                    placeholder="Phone"
                    :disabled="sending"
                />
                <input
                    v-model.trim="form.subject"
                    class="contact-input"
                    type="text"
                    placeholder="Subject"
                    :disabled="sending"
                />
                <textarea
                    v-model.trim="form.message"
                    class="contact-input contact-textarea"
                    placeholder="Message"
                    rows="4"
                    :disabled="sending"
                ></textarea>

                <button
                    type="submit"
                    class="contact-send"
                    :disabled="!canSend || sending"
                >
                    {{ sending ? "Sending…" : "Send" }}
                </button>

                <p v-if="error" class="contact-error">{{ error }}</p>
            </form>

            <!-- Sent confirmation state -->
            <div v-else class="contact-success">
                <p>
                    We've received your message and will reply to you as
                    soon as possible.
                </p>
            </div>
        </div>
    </transition>
</template>

<script>
export default {
    name: "ContactWidget",
    data() {
        return {
            open: false,
            sent: false,
            sending: false,
            error: "",
            form: {
                name: "",
                email: "",
                phone: "",
                subject: "",
                message: "",
            },
        };
    },
    computed: {
        canSend() {
            return (
                this.form.name &&
                this.form.email &&
                this.form.message
            );
        },
    },
    methods: {
        toggle() {
            this.open = !this.open;
        },
        resetForm() {
            this.form = {
                name: "",
                email: "",
                phone: "",
                subject: "",
                message: "",
            };
            this.sent = false;
            this.error = "";
        },
        async submit() {
            if (!this.canSend || this.sending) return;
            this.sending = true;
            this.error = "";
            try {
                const res = await fetch("/api/contact", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(this.form),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    throw new Error(
                        err.error || "Failed to send your message.",
                    );
                }
                this.sent = true;
            } catch (err) {
                this.error = err.message;
            } finally {
                this.sending = false;
            }
        },
    },
    watch: {
        // Reset back to a fresh form once the panel is fully closed after a send.
        open(isOpen) {
            if (!isOpen && this.sent) {
                // Delay so the close transition isn't interrupted by content swap.
                setTimeout(() => this.resetForm(), 250);
            }
        },
    },
};
</script>

<style scoped>
/* --- Floating action button --- */
.contact-fab {
    position: fixed;
    bottom: 24px;
    right: 24px;
    width: 52px;
    height: 52px;
    border-radius: 50%;
    background: var(--accent);
    border: none;
    color: #ffffff;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    box-shadow: var(--shadow-card);
    transition:
        transform 0.2s ease,
        background 0.2s ease;
    z-index: 1000;
}

.contact-fab:hover {
    transform: translateY(-2px);
    background: var(--accent-hover);
}

.contact-fab:active {
    background: var(--accent-active);
}

/* --- Popup panel --- */
.contact-panel {
    position: fixed;
    bottom: 88px;
    right: 24px;
    width: 320px;
    max-width: calc(100vw - 48px);
    background: var(--accent);
    border-radius: var(--radius-lg);
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25);
    padding: 22px 20px 24px;
    z-index: 1000;
}

.contact-title {
    color: #ffffff;
    font-size: 22px;
    font-weight: 700;
    text-align: center;
    margin-bottom: 18px;
    letter-spacing: -0.2px;
}

/* --- Form --- */
.contact-form {
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.contact-input {
    width: 100%;
    padding: 11px 14px;
    background: #ffffff;
    border: 1px solid transparent;
    border-radius: var(--radius-md);
    color: var(--text-primary);
    font-family: var(--font-sans);
    font-size: 14px;
    outline: none;
    transition:
        box-shadow 0.2s ease,
        border-color 0.2s ease;
}

.contact-input::placeholder {
    color: var(--text-muted);
}

.contact-input:focus {
    border-color: #ffffff;
    box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.3);
}

.contact-input:disabled {
    opacity: 0.7;
    cursor: not-allowed;
}

.contact-textarea {
    resize: vertical;
    min-height: 96px;
    line-height: 1.5;
}

.contact-send {
    width: 100%;
    padding: 12px;
    margin-top: 4px;
    background: var(--accent-hover);
    color: #ffffff;
    border: none;
    border-radius: var(--radius-md);
    font-family: var(--font-sans);
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
    transition:
        background 0.2s ease,
        opacity 0.2s ease;
}

.contact-send:hover:not(:disabled) {
    background: #4f6068;
}

.contact-send:disabled {
    opacity: 0.55;
    cursor: not-allowed;
}

.contact-error {
    color: #fff;
    background: rgba(220, 38, 38, 0.55);
    font-size: 12px;
    text-align: center;
    padding: 8px 10px;
    border-radius: var(--radius-sm);
}

/* --- Success state --- */
.contact-success {
    min-height: 220px;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0 8px;
}

.contact-success p {
    color: #ffffff;
    font-size: 15px;
    font-weight: 600;
    line-height: 1.55;
    text-align: center;
}

/* --- Transition --- */
.contact-pop-enter-active,
.contact-pop-leave-active {
    transition:
        opacity 0.2s ease,
        transform 0.2s ease;
}

.contact-pop-enter-from,
.contact-pop-leave-to {
    opacity: 0;
    transform: translateY(12px) scale(0.97);
}
</style>
