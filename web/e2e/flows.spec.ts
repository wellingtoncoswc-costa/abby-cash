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

test('categorias, lançamento com edição/exclusão, compra parcelada e preferências', async ({ page }) => {
  test.setTimeout(90_000)
  page.on('dialog', (d) => void d.accept())
  const mail = email('c')
  await register(page, process.env.E2E_INVITE_3!, mail)
  await login(page, mail)
  await page.getByRole('link', { name: 'Primeiros passos' }).click()
  await page.getByLabel('Nome da conta').fill('Nubank')
  await page.getByRole('button', { name: 'Adicionar conta' }).click()
  await expect(page.getByText('Nubank · R$ 0,00')).toBeVisible()
  await page.getByLabel('Nome do cartão').fill('Visa')
  await page.getByRole('button', { name: 'Adicionar cartão' }).click()
  await expect(page.getByText('Cartão adicionado.')).toBeVisible()

  await page.getByRole('link', { name: 'Categorias' }).click()
  await page.getByLabel('Nome da nova categoria').fill('Mercado e Feira')
  await page.getByRole('button', { name: 'Criar categoria' }).click()
  await expect(page.getByRole('listitem').filter({ hasText: /^Mercado e Feira/ })).toBeVisible()

  await page.getByRole('link', { name: 'Lançamentos' }).click()
  await page.getByLabel('Valor (R$)', { exact: true }).fill('45,00')
  await page.getByLabel('Descrição', { exact: true }).fill('Compras')
  await page.getByLabel('Categoria').first().selectOption({ label: 'Mercado e Feira' })
  await page.locator('label', { hasText: /^Conta/ }).first().locator('select').selectOption({ label: 'Nubank' })
  await page.getByRole('button', { name: 'Salvar', exact: true }).click()
  const item = page.getByRole('button', { name: 'Abrir Compras' })
  await expect(item).toContainText('Mercado e Feira')
  await item.click()
  await page.getByRole('button', { name: 'Editar lançamento' }).click()
  await page.getByLabel('Descrição (edição)').fill('Feira')
  await page.getByRole('button', { name: 'Salvar alterações' }).click()
  await page.getByRole('button', { name: 'Abrir Feira' }).click()
  await page.getByRole('button', { name: 'Editar lançamento' }).click()
  await page.getByRole('button', { name: 'Excluir' }).click()
  await expect(page.getByText('Nenhum lançamento.')).toBeVisible()

  await page.getByLabel('Cartão').first().selectOption({ label: 'Visa' })
  await page.getByLabel('Valor total (R$)').fill('300,00')
  await page.getByLabel('Parcelas').fill('3')
  await page.getByRole('button', { name: 'Lançar compra' }).click()
  await expect(page.getByRole('status')).toContainText('3x de R$ 100,00')

  await page.getByRole('link', { name: 'Configurações' }).click()
  await page.getByLabel('Horário dos lembretes').fill('08:30')
  await page.getByLabel('Receber resumo semanal').check()
  await page.getByRole('button', { name: 'Salvar preferências' }).click()
  await expect(page.getByText('Preferências salvas.')).toBeVisible()
  await page.reload()
  await expect(page.getByLabel('Horário dos lembretes')).toHaveValue('08:30')
  await expect(page.getByRole('link', { name: 'Admin' })).toHaveCount(0)
})
