(() => {
  const bridge = window.__ZAOMENG_LEGACY_BRIDGE__;
  const vue = window.Vue;
  const host = document.getElementById("composer-vue-root");
  const stage = document.getElementById("turn-stage");
  if (!bridge || !vue || !host || !stage) {
    return;
  }

  const { createApp, computed, onBeforeUnmount, onMounted, ref, watch, nextTick } = vue;

  function resizeComposerTextarea(node) {
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, 160)}px`;
  }

  function composerActions() {
    const tools = window.__ZAOMENG_UI_BRIDGE_TOOLS__ || {};
    if (typeof tools.readLegacyActionBridge === "function") {
      return tools.readLegacyActionBridge("__ZAOMENG_COMPOSER_ACTIONS__");
    }
    return window.__ZAOMENG_COMPOSER_ACTIONS__ || {};
  }

  function normalizeKind(kind) {
    return String(kind || "").trim() === "narration" ? "narration" : "dialogue";
  }

  createApp({
    setup() {
      const snapshot = ref(bridge.getSnapshot ? bridge.getSnapshot() : {});
      const unsubscribe = bridge.subscribe((nextSnapshot) => {
        snapshot.value = nextSnapshot || {};
      });

      onBeforeUnmount(() => {
        unsubscribe();
      });

      const composer = computed(() => snapshot.value.composer || {});
      const session = computed(() => snapshot.value.currentDialogueSession || {});
      const mode = computed(() => String(composer.value.mode || session.value.mode || session.value?.session_card?.mode || "").trim());
      const draft = ref("");
      const draftKind = ref("dialogue");
      const textareaRef = ref(null);
      watch(
        () => composer.value.placeholder,
        () => {
          nextTick(() => resizeComposerTextarea(textareaRef.value));
        }
      );
      watch(
        () => composer.value.message,
        (nextMessage) => {
          draft.value = String(nextMessage || "");
          nextTick(() => resizeComposerTextarea(textareaRef.value));
        },
        { immediate: true }
      );
      watch(
        () => composer.value.kind,
        (nextKind) => {
          draftKind.value = normalizeKind(nextKind);
        },
        { immediate: true }
      );
      watch(
        mode,
        (nextMode) => {
          if (String(nextMode || "").trim() === "observe") {
            setKind("narration");
          }
        },
        { immediate: true }
      );
      const placeholder = computed(() => String(composer.value.placeholder || ""));
      const quickReplies = computed(() => (Array.isArray(composer.value.quickReplies) ? composer.value.quickReplies : []));
      const disabled = computed(() => Boolean(composer.value.disabled));
      const suggestHidden = computed(() => Boolean(composer.value.suggestHidden) || mode.value === "observe");
      const showKindToggle = computed(() => mode.value !== "observe");
      const suggestDisabled = computed(() => Boolean(composer.value.suggestDisabled));
      const sendDisabled = computed(() => Boolean(composer.value.sendDisabled));

      onMounted(() => {
        stage.classList.add("has-vue-island");
        host.classList.remove("hidden");
        nextTick(() => resizeComposerTextarea(textareaRef.value));
      });

      function setDraftValue(value, options = {}) {
        draft.value = String(value || "");
        const actions = composerActions();
        if (typeof actions.setDraft === "function") {
          actions.setDraft(draft.value, options);
        }
        nextTick(() => resizeComposerTextarea(textareaRef.value));
      }

      function onDraftInput(event) {
        setDraftValue(event?.target?.value || "");
      }

      function setKind(nextKind) {
        draftKind.value = normalizeKind(nextKind);
        const actions = composerActions();
        if (typeof actions.setKind === "function") {
          actions.setKind(draftKind.value);
        }
      }

      function send() {
        const actions = composerActions();
        if (typeof actions.send === "function") {
          const sendKind = mode.value === "observe" ? "narration" : draftKind.value;
          actions.send(draft.value, sendKind);
        }
      }

      function suggest() {
        const actions = composerActions();
        if (typeof actions.suggest === "function") {
          actions.suggest();
        }
      }

      function quickReply(value) {
        const actions = composerActions();
        if (typeof actions.quickReply === "function") {
          actions.quickReply(value);
        }
      }

      function handleEnter(event) {
        if (event.key !== "Enter" || event.shiftKey) return;
        event.preventDefault();
        if (!sendDisabled.value) {
          send();
        }
      }

      return {
        disabled,
        draft,
        draftKind,
        textareaRef,
        onDraftInput,
        handleEnter,
        placeholder,
        quickReplies,
        quickReply,
        send,
        sendDisabled,
        showKindToggle,
        setDraftValue,
        setKind,
        suggest,
        suggestDisabled,
        suggestHidden,
      };
    },
    template: `
      <div class="composer-vue-shell">
        <div v-if="quickReplies.length" class="quick-reply-row">
          <button
            v-for="item in quickReplies"
            :key="item.label + ':' + item.value"
            type="button"
            class="quick-reply-chip"
            :disabled="disabled"
            @click="quickReply(item.value)"
          >
            {{ item.label }}
          </button>
        </div>

        <div class="composer-main composer-main-vue">
          <div v-if="showKindToggle" class="composer-kind-toggle" role="group" aria-label="输入类型">
            <button
              type="button"
              class="kind-chip"
              :class="{ active: draftKind === 'dialogue' }"
              @click="setKind('dialogue')"
            >
              台词
            </button>
            <button
              type="button"
              class="kind-chip"
              :class="{ active: draftKind === 'narration' }"
              @click="setKind('narration')"
            >
              剧情推动
            </button>
          </div>

          <textarea
            ref="textareaRef"
            class="composer-textarea"
            rows="2"
            :value="draft"
            :placeholder="placeholder"
            :disabled="disabled"
            @input="onDraftInput"
            @keydown="handleEnter"
          ></textarea>

          <div class="composer-actions">
            <button
              v-if="!suggestHidden"
              type="button"
              class="composer-icon-button"
              aria-label="帮我续一句"
              title="帮我续一句"
              :disabled="suggestDisabled"
              @click="suggest"
            >
              ✨
            </button>
            <button
              type="button"
              class="send-button"
              aria-label="送出"
              :disabled="sendDisabled"
              @click="send"
            >
              送出
            </button>
          </div>
        </div>
      </div>
    `,
  }).mount(host);
})();
