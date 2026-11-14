import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/login', component: () => import('./views/Login.vue') },
  { path: '/', component: () => import('./views/Jobs.vue') },
  { path: '/applications', component: () => import('./views/Applications.vue') },
  { path: '/resumes', component: () => import('./views/Resumes.vue') },
  { path: '/settings', component: () => import('./views/Settings.vue') },
  { path: '/admin', component: () => import('./views/Admin.vue') },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  const authed = !!localStorage.getItem('token')
  if (to.path !== '/login' && !authed) return '/login'
  if (to.path === '/login' && authed) return '/'
})

export default router
