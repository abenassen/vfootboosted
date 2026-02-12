const results = [
  {
    title: 'SportyBlocks League',
    date: '08/08/2023',
    events: [
      {
        id: 1,
        teams: [
          {
            name: 'GLD',
            color: {
              primary: 'text-team-golden-primary',
              secondary: 'bg-team-golden-secondary',
            },
            outcome: 'win',
            score: 2,
          },
          {
            name: 'EMR',
            color: {
              primary: 'text-team-emerald-primary',
              secondary: 'bg-team-emerald-secondary',
            },
            outcome: 'loss',
            score: 0,
          },
        ],
      },
      {
        id: 2,
        teams: [
          {
            name: 'AQU',
            color: {
              primary: 'text-team-aqua-primary',
              secondary: 'bg-team-aqua-secondary',
            },
            outcome: 'draw',
            score: 1,
          },
          {
            name: 'PUR',
            color: {
              primary: 'text-team-purple-primary',
              secondary: 'bg-team-purple-secondary',
            },
            outcome: 'draw',
            score: 1,
          },
        ],
      },
      {
        id: 3,
        teams: [
          {
            name: 'CRI',
            color: {
              primary: 'text-team-crimson-primary',
              secondary: 'bg-team-crimson-secondary',
            },
            outcome: 'loss',
            score: 1,
          },
          {
            name: 'BLU',
            color: {
              primary: 'text-team-blue-primary',
              secondary: 'bg-team-blue-secondary',
            },
            outcome: 'win',
            score: 3,
          },
        ],
      },
    ],
  },
  {
    title: 'World League Tournament',
    date: '07/24/2023',
    events: [
      {
        id: 1,
        teams: [
          {
            name: 'PUR',
            color: {
              primary: 'text-team-purple-primary',
              secondary: 'bg-team-purple-secondary',
            },
            outcome: 'win',
            score: 4,
          },
          {
            name: 'GRE',
            color: {
              primary: 'text-team-green-primary',
              secondary: 'bg-team-green-secondary',
            },
            outcome: 'loss',
            score: 0,
          },
        ],
      },
      {
        id: 2,
        teams: [
          {
            name: 'AQU',
            color: {
              primary: 'text-team-aqua-primary',
              secondary: 'bg-team-aqua-secondary',
            },
            outcome: 'win',
            score: 3,
          },
          {
            name: 'SLV',
            color: {
              primary: 'text-team-silver-primary',
              secondary: 'bg-team-silver-secondary',
            },
            outcome: 'loss',
            score: 0,
          },
        ],
      },
    ],
  },
];

export default function LatestResults2() {
  return (
    <div className="mx-auto w-full px-5 sm:w-[380px]">
      <div className="rounded-3xl border border-custom-gray-200 bg-white px-8 py-7 dark:border-custom-gray-600 dark:bg-custom-gray-800">
        <div className="-mx-8 -mt-7 px-8 py-7">
          <h3 className="text-base/tight font-bold text-custom-gray-900 dark:text-white">Latest Results</h3>
        </div>
        <div className="-mx-8 -mt-0.5 -mb-7 overflow-hidden rounded-3xl">
          {results.map((result) => (
            <div
              key={result.title}
              className="mt-0.5 rounded-t-3xl bg-custom-gray-100 ring-1 ring-custom-gray-200 dark:bg-custom-gray-700 dark:ring-custom-gray-600"
            >
              <div className="flex justify-between px-8 py-4 text-xs/tight font-bold text-custom-gray-900 dark:text-white">
                <h4 className="">{result.title}</h4>
                <time dateTime="08-08-2024">{result.date}</time>
              </div>
              <div className="relative rounded-t-3xl bg-white ring-1 ring-custom-gray-200 after:absolute after:-bottom-[1px] after:h-px after:w-full after:bg-white dark:bg-custom-gray-800 dark:ring-custom-gray-600 dark:after:bg-custom-gray-800">
                {result.events.map((event) => (
                  <div
                    key={event.id}
                    className="grid grid-cols-2 gap-x-3 border-b border-custom-gray-200 px-8 py-4 last:border-b-0 dark:border-custom-gray-600"
                  >
                    {event.teams.map((team) => (
                      <div key={team.name} className="group flex items-center justify-between even:flex-row-reverse">
                        <div className="flex items-center gap-3 group-even:flex-row-reverse">
                          <figure className="relative -my-4 h-12 w-10 overflow-hidden group-odd:[clip-path:polygon(0_0,_100%_0,_100%_100%,_24%_100%)] group-even:[clip-path:polygon(0_0,_100%_0,_76%_100%,_0_100%)] md:h-14 md:w-11">
                            <svg
                              viewBox="0 0 420 420"
                              fill="none"
                              xmlns="http://www.w3.org/2000/svg"
                              className={`absolute top-1/2 aspect-square w-12 -translate-y-1/2 group-odd:end-0 group-even:start-0 md:w-14 ${team.color.primary}`}
                            >
                              <path
                                d="M201.646 416.137C144.946 389.951 97.469 343.545 60.543 278.221C30.33 224.771 13.58 169.737 4.849 132.979L0 112.558L20.478 108.517C29.676 106.701 36.353 98.519 36.353 89.064C36.353 87.535 36.171 85.986 35.811 84.46L31.579 64.862L68.813 56.045V18.129L83.947 14.518C125.355 4.884 167.706 0 210.202 0C252.699 0 294.762 4.884 336.17 14.518L351.208 18.129V56.045L388.444 64.862L384.015 84.461C383.657 85.986 383.572 87.538 383.572 89.064C383.572 98.519 390.297 106.701 399.497 108.517L420 112.558L415.161 132.981C406.428 169.739 389.684 224.774 359.473 278.221C322.549 343.545 275.075 389.95 218.367 416.141L210.01 420L201.646 416.137Z"
                                fill="currentColor"
                              />
                              <path
                                d="M210 26C249.08 26 288.199 30.49 326.273 39.344L330.666 40.365V44.899V76.042L357.217 82.392L362.729 83.71L361.421 89.253C360.846 91.694 360.555 94.187 360.555 96.66C360.555 111.915 371.342 125.116 386.206 128.049L392 129.194L390.628 134.969C382.592 168.782 367.193 219.379 339.47 268.405C306.042 327.514 263.28 369.405 212.366 392.909L210.001 394L207.635 392.908C156.723 369.404 113.959 327.513 80.531 268.404C52.807 219.379 37.408 168.782 29.373 134.968L28 129.193L33.795 128.048C48.658 125.115 59.446 111.914 59.446 96.659C59.446 94.185 59.154 91.692 58.579 89.252L57.272 83.709L62.784 82.391L89.335 76.041V44.898V40.365L93.727 39.344C131.802 30.49 170.921 26 210 26Z"
                                className="fill-custom-gray-900"
                              />
                              <path
                                d="M210 34C247.854 34 285.747 38.279 322.666 46.722V76.042V82.355L328.806 83.823L353.174 89.651C352.763 91.972 352.555 94.321 352.555 96.661C352.555 114.914 364.931 130.818 382.308 135.36C374.25 168.639 359.165 217.325 332.506 264.466C300.136 321.705 258.926 362.315 210.001 385.186C161.075 362.314 119.865 321.706 87.496 264.466C60.837 217.324 45.752 168.638 37.695 135.359C55.073 130.817 67.447 114.914 67.447 96.66C67.447 94.322 67.239 91.973 66.827 89.65L91.196 83.822L97.335 82.354V76.041V46.721C134.252 38.28 172.149 34 210 34ZM210 26C170.921 26 131.801 30.49 93.728 39.344L89.336 40.365V44.898V76.042L62.785 82.392L57.273 83.71L58.58 89.253C59.155 91.693 59.447 94.187 59.447 96.66C59.447 111.915 48.659 125.116 33.796 128.049L28 129.193L29.374 134.968C37.409 168.781 52.808 219.378 80.532 268.404C113.96 327.513 156.723 369.404 207.636 392.908L210.002 394L212.367 392.908C263.28 369.404 306.043 327.513 339.471 268.404C367.195 219.379 382.593 168.782 390.629 134.968L392.001 129.193L386.207 128.048C371.343 125.115 360.556 111.914 360.556 96.659C360.556 94.185 360.847 91.693 361.422 89.252L362.73 83.709L357.218 82.391L330.667 76.041V44.899V40.365L326.274 39.344C288.199 30.49 249.08 26 210 26Z"
                                className="fill-white"
                              />
                              <path
                                fillRule="evenodd"
                                clipRule="evenodd"
                                d="M210.044 114C210.044 114 254.447 142.648 304.491 145.051C304.491 145.051 309.988 171.923 307.221 198.278C307.221 198.278 290.07 198.51 271.19 193.843C271.19 193.843 272.964 183.446 272.282 177.209C272.282 177.209 233.793 170.418 210.044 156.694C210.044 156.694 176.743 171.387 148.354 177.209C148.354 177.209 147.671 197.724 152.175 213.249C152.175 213.249 187.661 208.121 210.044 197.17C210.044 197.17 251.399 215.883 305.038 217.131C305.038 217.131 282.199 303.81 210.044 338.001C210.044 338.001 163.094 319.519 135.797 272.021C135.797 272.021 156.36 271.283 175.732 266.654C176.721 268.349 192.58 281.955 210.044 293.092C210.044 293.092 238.889 281.727 255.903 247.625C255.903 247.625 227.878 244.113 210.044 236.537C210.044 236.537 169.281 250.767 127.061 252.617C127.061 252.617 103.859 207.151 115.051 144.498C115.051 144.498 168.007 144.497 210.044 114Z"
                                fill="currentColor"
                              />
                              <path
                                d="M218.323 65.462L210.24 49L202.157 65.462L184.081 68.102L197.16 80.916L194.073 99.009L210.24 90.467L226.406 99.009L223.319 80.916L236.398 68.102L218.323 65.462ZM148.835 90.709L142.5 77.807L136.165 90.709L122 92.777L132.25 102.819L129.831 117L142.5 110.305L155.17 117L152.75 102.82L163 92.777L148.835 90.709ZM298 92.777L283.835 90.709L277.5 77.807L271.165 90.709L256.999 92.777L267.25 102.819L264.83 117L277.5 110.305L290.17 117L287.75 102.82L298 92.777Z"
                                className="fill-white"
                              />
                            </svg>
                            <div
                              className={`absolute inset-0 -z-10 group-odd:[clip-path:polygon(0_0,_76%_0,_100%_100%,_24%_100%)] group-even:[clip-path:polygon(24%_0,_100%_0,_76%_100%,_0_100%)] ${team.color.secondary}`}
                            ></div>
                          </figure>
                          <div className="min-w-0 text-xs/tight font-bold text-custom-gray-900 dark:text-white">
                            <div className="truncate">{team.name}</div>
                          </div>
                        </div>
                        <div className="relative inline-flex items-center gap-x-2 text-sm/tight font-bold text-custom-gray-900 group-first:after:absolute group-first:after:start-full group-first:after:top-0 group-first:after:translate-x-1/2 group-first:after:content-['-'] dark:text-white">
                          <div>{team.score}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
