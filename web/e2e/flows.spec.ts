import { expect, test, type Page } from '@playwright/test'

const PASSWORD = 'senha-segura-123'
const email = (tag: string) => `${tag}-${Date.now()}@e2e-abby.com`

async function register(page: Page, invite: string, mail: string) {
  await page.goto('/cadastro')
  await page.getByLabel('Código do convite').fill(invite)
  await page.getByLabel('Nome').fill('Teste E2E')
  await page.getByLabel('E-mail').fill(mail)
  await page.getByLabel('Senha (mínimo 10 caracteres)').fill(PASSWORD)
  await page.getByRole('button', { name: 'Cadastrar' }).click()
  await expect(page).toHaveURL(/\/login$/)
}

async function login(page: Page, mail: string) {
  await page.getByLabel('E-mail').fill(mail)
  await page.getByLabel('Senha').fill(PASSWORD)
  await page.getByRole('button', { name: 'Entrar' }).click()
}

test('cadastro com convite → login → painel', async ({ page }) => {
  const mail = email('a')
  await register(page, process.env.E2E_INVITE_1!, mail)
  await login(page, mail)
  await expect(page.getByRole('heading', { name: /Painel de/ })).toBeVisible()
  await expect(page.getByText('Nenhum lançamento.')).toBeVisible()
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage }))).not.toMatch(/eyJ/) // sem token em storage
})

test('onboarding', async ({ page }) => {
  const mail = email('b')
  await register(page, process.env.E2E_INVITE_2!, mail)
  await login(page, mail)
  await page.getByRole('link', { name: 'Primeiros passos' }).click()
  await page.getByLabel('Nome da conta').fill('Nubank')
  await page.getByLabel('Saldo inicial (R$)').fill('1.500,00')
  await page.getByRole('button', { name: 'Adicionar conta' }).click()
  await expect(page.getByText('Nubank · R$ 1.500,00')).toBeVisible()
  await page.getByLabel('Nome do cartão').fill('Visa')
  await page.getByRole('button', { name: 'Adicionar cartão' }).click()
  await expect(page.getByText('Cartão adicionado.')).toBeVisible()
  await page.getByLabel('Teto do mês (R$)').fill('3.000,00')
  await page.getByRole('button', { name: 'Salvar teto' }).click()
  await expect(page.getByText('Gasto R$ 0,00 de R$ 3.000,00')).toBeVisible()
  await page.getByRole('button', { name: 'Vincular Telegram' }).click()
  await expect(page.getByRole('status')).toContainText(/\d{6}/)
})
