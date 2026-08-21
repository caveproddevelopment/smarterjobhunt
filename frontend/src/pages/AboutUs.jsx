import Navbar from '../components/Navbar'
import Footer from '../components/Footer'

export default function AboutUs() {
  return (
    <div className="min-h-screen flame-gradient">
      <div className="mx-auto min-h-screen max-w-6xl bg-paper shadow-2xl shadow-ink/10">
        <Navbar />

        <main className="mx-auto max-w-3xl px-6 py-16">
          <p className="text-sm font-semibold uppercase tracking-wide text-ember">About us</p>
          <h1 className="mt-2 font-display text-3xl font-semibold text-ink md:text-4xl">
            The studio behind JobBeggar
          </h1>

          <div className="mt-8 space-y-6 text-base leading-relaxed text-ink-soft">
            <p>
              JobBeggar is built by <strong className="font-semibold text-ink">Caveman Productions
              Media</strong>, an independent studio based in Leander, Texas. We make animated shows,
              mobile apps, and small, purpose-built software tools. JobBeggar is the newest of those.
            </p>
            <p>
              I'm Monte, the guy running all of it. I've spent over twenty years leading large
              technology and product programs, most recently at Dell Technologies. Caveman
              Productions started in 2024 and it's grown into a real studio with a small team spread
              across the globe.
            </p>
            <p>
              Most of what we've built so far sits in the creative world — animation, illustration
              and publication. Our flagship series, <em>Uggalot</em>, is entirely hand-drawn, frame by
              frame, with real voice actors, several of them family. That's not an accident. We'd
              rather ship something slower and made by actual people than something faster and AI
              generated. We like quality. It makes us feel all warm and fuzzy.
            </p>
            <p>
              Software is the other half of what we do — solving problems that people really have and
              not worrying about what is trendy. Like JobBeggar. JobBeggar exists because I was job
              hunting. The tools I was being forced to use sucked. So I created a personal process and
              developed a set of personal agents that helped me. Just like Dr. Frankenstein, I liked
              my creation enough to give it to the world … that was probably a poor comparison.
            </p>
            <p>
              Bottom line, this tool is built because I had a real need and I happened to have a real
              company doing real things. No. Really.
            </p>
            <p>
              We're small on purpose. There's no marketing department dressing this up and no outside
              investors setting growth targets ahead of a product that actually works. If something
              here is broken or missing, tell us. We're the ones who fix it.
            </p>
          </div>
        </main>

        <Footer />
      </div>
    </div>
  )
}
