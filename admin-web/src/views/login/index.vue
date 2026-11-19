<template>
  <div class="hg-login">
    <main class="hg-login__card">
      <div class="hg-login__brand">
        <div class="hg-login__logo" aria-hidden="true">
          <svg
            viewBox="0 0 24 24"
            width="28"
            height="28"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
          >
            <path
              d="M12 3a5 5 0 0 0-5 5v3a5 5 0 0 0 10 0V8a5 5 0 0 0-5-5Z"
              stroke-linejoin="round"
            />
            <path d="M4 12h16" stroke-linecap="round" />
            <path d="M12 3v3" stroke-linecap="round" />
          </svg>
        </div>
        <h1 class="hg-login__title">校园头盔检测提醒助手</h1>
        <p class="hg-login__subtitle">管理后台</p>
      </div>

      <ElForm
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        class="hg-login__form"
        @submit.prevent="onSubmit"
      >
        <ElFormItem label="用户名" prop="username">
          <ElInput
            v-model="form.username"
            placeholder="请输入用户名"
            size="large"
            autocomplete="username"
            :prefix-icon="User"
          />
        </ElFormItem>

        <ElFormItem label="密码" prop="password">
          <ElInput
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            size="large"
            autocomplete="current-password"
            show-password
            :prefix-icon="Lock"
            @keyup.enter="onSubmit"
          />
        </ElFormItem>

        <p v-if="errorMessage" class="hg-login__error" role="alert">{{ errorMessage }}</p>

        <ElButton
          type="primary"
          size="large"
          class="hg-login__submit"
          native-type="submit"
          :loading="authStore.loading"
        >
          {{ authStore.loading ? '登录中' : '登录' }}
        </ElButton>
      </ElForm>
    </main>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ElButton,
  ElForm,
  ElFormItem,
  ElInput,
  type FormInstance,
  type FormRules,
} from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/api/types'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const formRef = ref<FormInstance>()
const errorMessage = ref('')

const form = reactive({
  username: '',
  password: '',
})

const rules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 32, message: '用户名长度为 3-32 个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 64, message: '密码长度为 6-64 个字符', trigger: 'blur' },
  ],
}

async function onSubmit(): Promise<void> {
  errorMessage.value = ''

  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  try {
    await authStore.login({ username: form.username, password: form.password })

    const redirect = route.query.redirect
    const target = typeof redirect === 'string' && redirect.startsWith('/') ? redirect : '/'
    await router.replace(target)
  } catch (error) {
    // 失败保留输入内容，仅提示错误
    errorMessage.value = error instanceof ApiError ? error.message : '登录失败，请检查网络后重试'
  }
}
</script>

<style scoped lang="scss">
.hg-login {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: var(--space-6);
  background-color: var(--color-bg);
}

.hg-login__card {
  width: 100%;
  max-width: 380px;
  padding: var(--space-8) var(--space-6);
  background-color: var(--color-surface);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-card);
}

.hg-login__brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-6);
}

.hg-login__logo {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  color: var(--color-surface);
  background-color: var(--color-primary);
  border-radius: var(--radius-lg);
}

.hg-login__title {
  margin: 0;
  font-size: var(--text-title-size);
  line-height: var(--text-title-line);
  font-weight: var(--text-title-weight);
  letter-spacing: var(--text-title-spacing);
  color: var(--color-text);
  text-align: center;
}

.hg-login__subtitle {
  font-size: var(--text-footnote-size);
  color: var(--color-text-3);
}

.hg-login__form {
  :deep(.el-form-item__label) {
    font-size: var(--text-footnote-size);
    font-weight: var(--text-subhead-weight);
    color: var(--color-text-2);
    padding-bottom: var(--space-1);
  }

  :deep(.el-input__wrapper) {
    border-radius: var(--radius-md);
  }

  :deep(.el-input__wrapper.is-focus) {
    box-shadow: 0 0 0 3px var(--color-primary-tint);
  }
}

.hg-login__error {
  margin-bottom: var(--space-3);
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-footnote-size);
  color: var(--color-danger);
  background-color: var(--color-danger-tint);
  border-radius: var(--radius-md);
}

.hg-login__submit {
  width: 100%;
  height: var(--control-height-touch);
  font-size: var(--text-body-size);
  font-weight: var(--text-subhead-weight);
  border-radius: var(--radius-lg);
}
</style>
