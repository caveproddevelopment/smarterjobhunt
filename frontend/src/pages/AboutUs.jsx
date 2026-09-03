import { useState } from 'react'
import Navbar from '../components/Navbar'
import Footer from '../components/Footer'
import { submitContactMessage } from '../lib/api'

export default function AboutUs() {
  const [formData, setFormData] = useState({
    name: '',
    email: '',
    subject: '',
    message: '',
    website: '', // honeypot -- stays empty for real users, see the hidden field below
  })

  const [status, setStatus] = useState('')
  const [errorMessage, setErrorMessage] = useState('')

  const handleChange = (e) => {
    const { name, value } = e.target

    setFormData((prev) => ({
      ...prev,
      [name]: value,
    }))
  }

  const handleSubmit = async (e) => {
    e.preventDefault()

    setStatus('sending')
    setErrorMessage('')

    try {
      await submitContactMessage(formData)

      setFormData({
        name: '',
        email: '',
        subject: '',
        message: '',
        website: '',
      })

      setStatus('success')
    } catch (error) {
      setErrorMessage(error.message)
      setStatus('error')
    }
  }

  return (
    <div className="min-h-screen flame-gradient">
      <div className="mx-auto min-h-screen max-w-6xl bg-paper shadow-2xl shadow-ink/10">
        <Navbar />

        <main className="mx-auto max-w-3xl px-6 py-16">
          <p className="text-sm font-semibold uppercase tracking-wide text-ember">
            About us
          </p>

          <h1 className="mt-2 font-display text-3xl font-semibold text-ink md:text-4xl">
            The studio behind JobBeggar
          </h1>

          <div className="mt-8 space-y-6 text-base leading-relaxed text-ink-soft">
            <p>
              JobBeggar is built by{' '}
              <strong className="font-semibold text-ink">
                Caveman Productions Media
              </strong>
              , an independent studio based in Leander, Texas. We make animated
              shows, mobile apps, and small, purpose-built software tools.
              JobBeggar is the newest of those.
            </p>

            <div className="flex flex-col gap-6 sm:flex-row sm:items-start">
              <img
                src="/images/monte%20about%20us%20pic.jpeg"
                alt="Monte, founder of Caveman Productions Media"
                className="h-40 w-40 shrink-0 rounded-2xl border border-line object-cover shadow-sm sm:h-44 sm:w-44"
              />
              <p>
                I'm Monte, the guy running all of it. I've spent over twenty years
                leading large technology and product programs, most recently at
                Dell Technologies. Caveman Productions started in 2024 and it's
                grown into a real studio with a small team spread across the globe.
              </p>
            </div>

            <p>
              Most of what we've built so far sits in the creative world —
              animation, illustration and publication. Our flagship series,
              <em> Uggalot</em>, is entirely hand-drawn, frame by frame, with
              real voice actors, several of them family.
            </p>

            <p>
              Software is the other half of what we do — solving problems that
              people really have and not worrying about what is trendy. Like
              JobBeggar.
            </p>

            <p>
              Bottom line, this tool is built because I had a real need and I
              happened to have a real company doing real things. No. Really.
            </p>

            <p>
              We're small on purpose. There's no marketing department dressing
              this up and no outside investors setting growth targets ahead of a
              product that actually works. If something here is broken or
              missing, tell us. We're the ones who fix it.
            </p>
          </div>

          {/* Contact Form */}
          <section id="contact" className="mt-16 border-t border-ink/10 pt-12">
            <p className="text-sm font-semibold uppercase tracking-wide text-ember">
              Contact us
            </p>

            <h2 className="mt-2 font-display text-2xl font-semibold text-ink md:text-3xl">
              Have a question or found something we should fix?
            </h2>

            <p className="mt-3 text-base leading-relaxed text-ink-soft">
              Send us a message and we'll get back to you as soon as we can.
            </p>

            <form onSubmit={handleSubmit} className="mt-8 space-y-5">
              {/* Honeypot -- hidden from real visitors, only a bot filling
                  every field blindly will trip it. Server silently drops
                  submissions where this is non-empty. */}
              <div className="hidden" aria-hidden="true">
                <label htmlFor="website">Leave this field blank</label>
                <input
                  id="website"
                  name="website"
                  type="text"
                  tabIndex={-1}
                  autoComplete="off"
                  value={formData.website}
                  onChange={handleChange}
                />
              </div>

              <div className="grid gap-5 md:grid-cols-2">
                <div>
                  <label
                    htmlFor="name"
                    className="mb-2 block text-sm font-semibold text-ink"
                  >
                    Name
                  </label>

                  <input
                    id="name"
                    name="name"
                    type="text"
                    required
                    value={formData.name}
                    onChange={handleChange}
                    placeholder="Your name"
                    className="w-full rounded-lg border border-ink/15 bg-white px-4 py-3 text-ink outline-none transition placeholder:text-ink-soft/50 focus:border-ember focus:ring-2 focus:ring-ember/20"
                  />
                </div>

                <div>
                  <label
                    htmlFor="email"
                    className="mb-2 block text-sm font-semibold text-ink"
                  >
                    Email
                  </label>

                  <input
                    id="email"
                    name="email"
                    type="email"
                    required
                    value={formData.email}
                    onChange={handleChange}
                    placeholder="you@example.com"
                    className="w-full rounded-lg border border-ink/15 bg-white px-4 py-3 text-ink outline-none transition placeholder:text-ink-soft/50 focus:border-ember focus:ring-2 focus:ring-ember/20"
                  />
                </div>
              </div>

              <div>
                <label
                  htmlFor="subject"
                  className="mb-2 block text-sm font-semibold text-ink"
                >
                  Subject
                </label>

                <select
                  id="subject"
                  name="subject"
                  required
                  value={formData.subject}
                  onChange={handleChange}
                  className="w-full rounded-lg border border-ink/15 bg-white px-4 py-3 text-ink outline-none transition focus:border-ember focus:ring-2 focus:ring-ember/20"
                >
                  <option value="">Select a subject</option>
                  <option value="general">General question</option>
                  <option value="bug">Report a problem</option>
                  <option value="feedback">Feedback / suggestion</option>
                  <option value="account">Account help</option>
                  <option value="business">Business inquiry</option>
                  <option value="other">Other</option>
                </select>
              </div>

              <div>
                <label
                  htmlFor="message"
                  className="mb-2 block text-sm font-semibold text-ink"
                >
                  Message
                </label>

                <textarea
                  id="message"
                  name="message"
                  required
                  rows={6}
                  value={formData.message}
                  onChange={handleChange}
                  placeholder="Tell us how we can help..."
                  className="w-full resize-y rounded-lg border border-ink/15 bg-white px-4 py-3 text-ink outline-none transition placeholder:text-ink-soft/50 focus:border-ember focus:ring-2 focus:ring-ember/20"
                />
              </div>

              <button
                type="submit"
                disabled={status === 'sending'}
                className="rounded-lg bg-ember px-6 py-3 text-sm font-semibold text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {status === 'sending' ? 'Sending...' : 'Send message'}
              </button>

              {status === 'success' && (
                <p className="text-sm font-medium text-green-700">
                  Thanks! Your message has been sent successfully.
                </p>
              )}

              {status === 'error' && (
                <p className="text-sm font-medium text-red-600">
                  {errorMessage || 'Something went wrong. Please try again.'}
                </p>
              )}
            </form>
          </section>
        </main>

        <Footer />
      </div>
    </div>
  )
}