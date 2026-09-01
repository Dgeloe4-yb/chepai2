<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  VOICE_ALERT_TYPES,
  assignUserEdgeBoxes,
  assignUserFeatures,
  createUser,
  fetchEdgeBoxes,
  fetchUserEdgeBoxes,
  fetchUserFeatures,
  fetchUsers,
  updateUser,
  type AppUser,
  type EdgeBox,
} from '@/api/client'

const loading = ref(false)
const users = ref<AppUser[]>([])
const boxes = ref<EdgeBox[]>([])

const createOpen = ref(false)
const createForm = ref({ username: '', password: '', displayName: '', role: 'USER' as 'USER' | 'SUPER_ADMIN' })

const assignOpen = ref(false)
const assignUser = ref<AppUser | null>(null)
const assignIds = ref<string[]>([])

const featureOpen = ref(false)
const featureUser = ref<AppUser | null>(null)
const featureKeys = ref<string[]>([])

function featureLabels(keys: string[] | undefined) {
  if (!keys?.length) return '未开通'
  return keys
    .map((k) => VOICE_ALERT_TYPES.find((t) => t.value === k)?.label ?? k)
    .join('、')
}

async function load() {
  loading.value = true
  try {
    users.value = await fetchUsers()
    boxes.value = await fetchEdgeBoxes()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function submitUser() {
  if (!createForm.value.username.trim() || createForm.value.password.length < 6) {
    ElMessage.warning('用户名必填，密码至少 6 位')
    return
  }
  await createUser({
    username: createForm.value.username.trim(),
    password: createForm.value.password,
    displayName: createForm.value.displayName.trim() || null,
    role: createForm.value.role,
  })
  ElMessage.success('已创建用户')
  createOpen.value = false
  createForm.value = { username: '', password: '', displayName: '', role: 'USER' }
  await load()
}

async function openAssign(row: AppUser) {
  assignUser.value = row
  const current = await fetchUserEdgeBoxes(row.id)
  assignIds.value = current.map((b) => b.id)
  assignOpen.value = true
}

async function saveAssign() {
  if (!assignUser.value) return
  await assignUserEdgeBoxes(assignUser.value.id, assignIds.value)
  ElMessage.success('已分配工控机')
  assignOpen.value = false
  await load()
}

async function openFeatures(row: AppUser) {
  featureUser.value = row
  featureKeys.value = [...(await fetchUserFeatures(row.id))]
  featureOpen.value = true
}

async function saveFeatures() {
  if (!featureUser.value) return
  await assignUserFeatures(featureUser.value.id, featureKeys.value)
  ElMessage.success('已保存功能，工控机约 30 秒内心跳同步')
  featureOpen.value = false
  await load()
}

async function toggleEnabled(row: AppUser) {
  await updateUser(row.id, { enabled: !row.enabled })
  await load()
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <el-button type="primary" @click="createOpen = true">新建用户</el-button>
      <el-button @click="load" :loading="loading">刷新</el-button>
    </div>

    <el-table :data="users" v-loading="loading" row-key="id" stripe style="width: 100%">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="username" label="账号" width="140" />
      <el-table-column prop="displayName" label="名称" />
      <el-table-column prop="role" label="角色" width="100">
        <template #default="{ row }">
          {{ row.role === 'SUPER_ADMIN' ? '超管' : '用户' }}
        </template>
      </el-table-column>
      <el-table-column label="开通功能" min-width="220">
        <template #default="{ row }">
          <span v-if="row.role === 'SUPER_ADMIN'" class="muted">全部</span>
          <span v-else>{{ featureLabels(row.features) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          {{ row.enabled ? '启用' : '停用' }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="280" fixed="right">
        <template #default="{ row }">
          <el-button v-if="row.role === 'USER'" link type="primary" @click="openFeatures(row)">
            开通功能
          </el-button>
          <el-button v-if="row.role === 'USER'" link type="primary" @click="openAssign(row)">
            分配工控机
          </el-button>
          <el-button link type="primary" @click="toggleEnabled(row)">
            {{ row.enabled ? '停用' : '启用' }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <h3 class="sub">已上线工控机（自动注册）</h3>
    <el-table :data="boxes" row-key="id" stripe style="width: 100%">
      <el-table-column prop="id" label="ID" width="200" />
      <el-table-column prop="name" label="名称" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.online ? 'success' : 'info'" size="small">
            {{ row.online ? '在线' : '离线' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="最近心跳" width="180">
        <template #default="{ row }">
          {{ row.lastSeenAt ? String(row.lastSeenAt).replace('T', ' ').slice(0, 19) : '—' }}
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="createOpen" title="新建用户" width="480px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="账号" required>
          <el-input v-model="createForm.username" />
        </el-form-item>
        <el-form-item label="密码" required>
          <el-input v-model="createForm.password" type="password" show-password />
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="createForm.displayName" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="createForm.role" style="width: 100%">
            <el-option label="用户" value="USER" />
            <el-option label="超管" value="SUPER_ADMIN" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" @click="submitUser">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="assignOpen" title="分配工控机" width="480px" destroy-on-close>
      <p class="hint">用户：{{ assignUser?.username }}</p>
      <el-checkbox-group v-model="assignIds">
        <el-checkbox v-for="b in boxes" :key="b.id" :label="b.id">
          {{ b.name }} ({{ b.id }})
        </el-checkbox>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="assignOpen = false">取消</el-button>
        <el-button type="primary" @click="saveAssign">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="featureOpen" title="开通功能" width="520px" destroy-on-close>
      <p class="hint">
        用户：{{ featureUser?.username }}。关闭后约 30 秒内心跳同步到该用户绑定的工控机；一台工控机绑多名用户时取并集。不卸载模型，不影响 NPU 长跑。
      </p>
      <el-checkbox-group v-model="featureKeys">
        <el-checkbox v-for="t in VOICE_ALERT_TYPES" :key="t.value" :label="t.value">
          {{ t.label }}
        </el-checkbox>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="featureOpen = false">取消</el-button>
        <el-button type="primary" @click="saveFeatures">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar {
  margin-bottom: 12px;
  display: flex;
  gap: 8px;
}
.sub {
  margin: 24px 0 12px;
  font-size: 15px;
}
.hint {
  margin: 0 0 12px;
  color: var(--el-text-color-secondary);
}
.muted {
  color: var(--el-text-color-secondary);
}
</style>
