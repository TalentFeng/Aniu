<template>
  <div class="admin-page stack-layout">
    <section class="panel">
      <div class="panel-header">
        <div>
          <p class="eyebrow">Admin</p>
          <h2>用户管理</h2>
        </div>
        <button class="button secondary" type="button" @click="loadAll" :disabled="loading">
          刷新
        </button>
      </div>

      <form class="admin-form" @submit.prevent="handleCreateUser">
        <label class="field">
          <span>用户名</span>
          <input v-model="createForm.username" type="text" />
        </label>
        <label class="field">
          <span>密码</span>
          <input v-model="createForm.password" type="password" />
        </label>
        <label class="field">
          <span>角色</span>
          <select v-model="createForm.role">
            <option value="user">普通用户</option>
            <option value="admin">管理员</option>
          </select>
        </label>
        <label class="field">
          <span>初始 Credit</span>
          <input v-model.number="createForm.credit_balance" type="number" min="0" />
        </label>
        <button class="button primary" type="submit" :disabled="loading">创建用户</button>
      </form>

      <p v-if="message" class="success-text">{{ message }}</p>
      <p v-if="errorMessage" class="hero-error">{{ errorMessage }}</p>

      <div class="admin-table">
        <div class="admin-table-head">
          <span>用户</span>
          <span>角色</span>
          <span>Credit</span>
          <span>状态</span>
          <span>操作</span>
        </div>
        <article v-for="item in users" :key="item.id" class="admin-table-row">
          <span>{{ item.username }}</span>
          <span>{{ item.role === 'admin' ? '管理员' : '普通用户' }}</span>
          <span>{{ item.credit_balance }}</span>
          <span>{{ item.is_active ? '启用中' : '已停用' }}</span>
          <div class="admin-actions">
            <button class="button secondary" type="button" @click="toggleUser(item)">
              {{ item.is_active ? '禁用' : '启用' }}
            </button>
            <button class="button secondary" type="button" @click="rechargeUser(item, 10)">+10</button>
            <button class="button secondary" type="button" @click="rechargeUser(item, 100)">+100</button>
          </div>
        </article>
      </div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <div>
          <p class="eyebrow">Pricing</p>
          <h2>模型定价</h2>
        </div>
        <button class="button secondary" type="button" @click="addPricingRow">新增模型</button>
      </div>

      <div class="admin-table">
        <div class="admin-table-head pricing-grid">
          <span>模型名</span>
          <span>Credit</span>
          <span>启用</span>
        </div>
        <article v-for="(item, index) in pricing" :key="`${item.model_name}-${index}`" class="admin-table-row pricing-grid">
          <input v-model="item.model_name" type="text" />
          <input v-model.number="item.credit_cost" type="number" min="0" />
          <label class="toggle-field">
            <input v-model="item.is_active" type="checkbox" />
            <span>{{ item.is_active ? '启用' : '停用' }}</span>
          </label>
        </article>
      </div>

      <div class="admin-footer">
        <button class="button primary" type="button" @click="savePricing" :disabled="loading">
          保存定价
        </button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { api } from '@/services/api'
import type { AdminUser, ModelPricing } from '@/types'

const loading = ref(false)
const message = ref('')
const errorMessage = ref('')
const users = ref<AdminUser[]>([])
const pricing = ref<Array<Pick<ModelPricing, 'model_name' | 'credit_cost' | 'is_active'>>>([])

const createForm = reactive({
  username: '',
  password: '',
  role: 'user' as 'admin' | 'user',
  credit_balance: 0,
})

async function loadAll() {
  loading.value = true
  errorMessage.value = ''
  try {
    const [userList, pricingList] = await Promise.all([
      api.listUsers(),
      api.listModelPricing(),
    ])
    users.value = userList
    pricing.value = pricingList.map((item) => ({
      model_name: item.model_name,
      credit_cost: item.credit_cost,
      is_active: item.is_active,
    }))
  } catch (error) {
    errorMessage.value = (error as Error).message
  } finally {
    loading.value = false
  }
}

async function handleCreateUser() {
  loading.value = true
  errorMessage.value = ''
  message.value = ''
  try {
    await api.createUser({
      username: createForm.username.trim(),
      password: createForm.password,
      role: createForm.role,
      credit_balance: createForm.credit_balance,
    })
    createForm.username = ''
    createForm.password = ''
    createForm.role = 'user'
    createForm.credit_balance = 0
    message.value = '用户已创建。'
    await loadAll()
  } catch (error) {
    errorMessage.value = (error as Error).message
  } finally {
    loading.value = false
  }
}

async function toggleUser(item: AdminUser) {
  loading.value = true
  errorMessage.value = ''
  message.value = ''
  try {
    await api.updateUserStatus(item.id, { is_active: !item.is_active })
    message.value = '用户状态已更新。'
    await loadAll()
  } catch (error) {
    errorMessage.value = (error as Error).message
  } finally {
    loading.value = false
  }
}

async function rechargeUser(item: AdminUser, amount: number) {
  loading.value = true
  errorMessage.value = ''
  message.value = ''
  try {
    await api.adjustUserCredit(item.id, { amount, note: `Admin recharge +${amount}` })
    message.value = 'Credit 已调整。'
    await loadAll()
  } catch (error) {
    errorMessage.value = (error as Error).message
  } finally {
    loading.value = false
  }
}

function addPricingRow() {
  pricing.value.push({
    model_name: '',
    credit_cost: 0,
    is_active: true,
  })
}

async function savePricing() {
  loading.value = true
  errorMessage.value = ''
  message.value = ''
  try {
    await api.replaceModelPricing(
      pricing.value
        .map((item) => ({
          model_name: item.model_name.trim(),
          credit_cost: Math.max(0, Number(item.credit_cost) || 0),
          is_active: item.is_active,
        }))
        .filter((item) => item.model_name),
    )
    message.value = '模型定价已保存。'
    await loadAll()
  } catch (error) {
    errorMessage.value = (error as Error).message
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadAll()
})
</script>

<style scoped>
.admin-page {
  gap: 24px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
}

.eyebrow {
  margin: 0 0 6px;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.admin-form {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}

.admin-table {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.admin-table-head,
.admin-table-row {
  display: grid;
  grid-template-columns: 1.4fr 1fr 1fr 1fr 1.4fr;
  gap: 12px;
  align-items: center;
}

.admin-table-head {
  font-size: 12px;
  color: var(--text-muted);
}

.admin-table-row {
  padding: 14px 16px;
  border: 1px solid var(--border-soft);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.7);
}

.pricing-grid {
  grid-template-columns: 2fr 1fr 1fr;
}

.admin-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.toggle-field {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.admin-footer {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

.success-text {
  color: #0f7a4b;
}

@media (max-width: 900px) {
  .admin-table-head,
  .admin-table-row,
  .pricing-grid {
    grid-template-columns: 1fr;
  }
}
</style>
